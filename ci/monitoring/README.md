# Логи приложения в Grafana

Prometheus хранит метрики и логи хранить не умеет — для логов нужен отдельный
стек. Минимальный набор поверх того, что уже есть в кластере:

| Компонент | Роль | Куда ставится |
|---|---|---|
| **Loki** | хранилище логов, аналог Prometheus для текста | `monitoring`, один под |
| **Grafana Alloy** | сборщик: читает логи подов с ноды и шлёт в Loki | `monitoring`, DaemonSet |
| **Grafana** | просмотр; скорее всего уже стоит вместе с Prometheus | — |

```
поды rtt ──логи на диск ноды──▶ /var/log/pods ──▶ Alloy (DaemonSet)
                                                    │ push
                                                    ▼
                              Grafana ◀──запросы── Loki (PVC)
```

> **Promtail не использовать.** С 2 марта 2026 он EOL, сбор логов переехал
> в Grafana Alloy. Чарт `grafana/promtail` ещё лежит в репозитории, но новые
> установки делать на нём не нужно.

## 0. Проверить, что уже есть

```bash
kubectl get pods -A | grep -iE "grafana|prometheus|loki|alloy"
```

Если Prometheus ставился чартом `kube-prometheus-stack`, Grafana уже есть
в том же namespace (обычно `monitoring`) — отдельно её ставить не нужно.
Дальше по тексту namespace считается `monitoring`, поправьте под свой.

## 1. Loki

Чарт `loki` активно развивается в репозитории `grafana-community`
(в старом `grafana/helm-charts` он заморожен на версии 7.3.0):

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
```

Значения по умолчанию рассчитаны на объектное хранилище и кластер из многих нод —
для одной ноды k3s нужно явно включить монолитный режим, файловое хранилище
и выключить всё лишнее (memcached-кеши, gateway, canary, тесты), иначе чарт
поднимет десяток подов.

`ci/monitoring/loki-values.yaml`:

```yaml
deploymentMode: Monolithic

loki:
  # один арендатор: Grafana сможет ходить без заголовка X-Scope-OrgID
  auth_enabled: false
  commonConfig:
    replication_factor: 1
  storage:
    type: filesystem
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: filesystem
        schema: v13
        index:
          prefix: index_
          period: 24h
  limits_config:
    retention_period: 720h          # 30 дней
    volume_enabled: true
    # запас на всплески логов воркера
    ingestion_rate_mb: 8
    ingestion_burst_size_mb: 16
  compactor:
    working_directory: /var/loki/compactor
    retention_enabled: true
    delete_request_store: filesystem

singleBinary:
  replicas: 1
  persistence:
    enabled: true
    size: 10Gi
    # storageClass: local-path      # в k3s по умолчанию local-path
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      memory: 1Gi

# нули обязательны: иначе чарт поднимет поды для распределённого режима
read:
  replicas: 0
write:
  replicas: 0
backend:
  replicas: 0

# всё это не нужно на одной ноде и съедает память
gateway:
  enabled: false
chunksCache:
  enabled: false
resultsCache:
  enabled: false
lokiCanary:
  enabled: false
test:
  enabled: false
```

```bash
helm upgrade --install loki grafana-community/loki \
  -n monitoring --create-namespace \
  -f ci/monitoring/loki-values.yaml

kubectl -n monitoring get pods,svc,pvc | grep loki
```

Адрес для datasource и для Alloy — сервис `loki` на порту 3100:
`http://loki.monitoring.svc.cluster.local:3100`
(проверьте имя: `kubectl -n monitoring get svc`).

## 2. Alloy — сбор логов

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update
```

`ci/monitoring/alloy-values.yaml`:

```yaml
controller:
  type: daemonset

alloy:
  # доступ к /var/log/pods на ноде, где лежат логи контейнеров
  mounts:
    varlog: true
  resources:
    requests:
      cpu: 50m
      memory: 128Mi
    limits:
      memory: 256Mi
  configMap:
    content: |-
      discovery.kubernetes "pods" {
        role = "pod"
      }

      discovery.relabel "pods" {
        targets = discovery.kubernetes.pods.targets

        // метки, по которым потом фильтруем в Grafana
        rule {
          source_labels = ["__meta_kubernetes_namespace"]
          target_label  = "namespace"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_label_app"]
          target_label  = "app"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_name"]
          target_label  = "pod"
        }
        rule {
          source_labels = ["__meta_kubernetes_pod_container_name"]
          target_label  = "container"
        }

        // путь к файлу логов контейнера на ноде
        rule {
          source_labels = ["__meta_kubernetes_pod_uid", "__meta_kubernetes_pod_container_name"]
          separator     = "/"
          action        = "replace"
          replacement   = "/var/log/pods/*$1/*.log"
          target_label  = "__path__"
        }
      }

      local.file_match "pods" {
        path_targets = discovery.relabel.pods.output
      }

      loki.source.file "pods" {
        targets    = local.file_match.pods.targets
        forward_to = [loki.process.pods.receiver]
      }

      loki.process "pods" {
        // снять обёртку формата CRI: время, поток, флаг многострочности
        stage.cri {}

        // текущий формат приложения: "2026-10-16 07:12:03,123 INFO src.module: текст"
        stage.regex {
          expression = "^\\S+ \\S+ (?P<level>[A-Z]+) (?P<logger>\\S+): "
        }
        stage.labels {
          values = {
            level = "level",
          }
        }

        forward_to = [loki.write.default.receiver]
      }

      loki.write "default" {
        endpoint {
          url = "http://loki.monitoring.svc.cluster.local:3100/loki/api/v1/push"
        }
      }
```

```bash
helm upgrade --install alloy grafana/alloy \
  -n monitoring -f ci/monitoring/alloy-values.yaml

kubectl -n monitoring logs ds/alloy | tail -20
```

RBAC на чтение подов чарт создаёт сам (`rbac.create: true` по умолчанию).

Если нужны логи только приложения, а не всего кластера, добавьте в
`discovery.relabel "pods"` отсев по namespace:

```alloy
rule {
  source_labels = ["__meta_kubernetes_namespace"]
  regex         = "rtt"
  action        = "keep"
}
```

## 3. Подключить Loki к Grafana

Если Grafana стоит из `kube-prometheus-stack`, её sidecar сам подхватывает
datasource из ConfigMap с нужной меткой — манифест переживёт обновление чарта:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: grafana-datasource-loki
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  loki.yaml: |
    apiVersion: 1
    datasources:
      - name: Loki
        type: loki
        access: proxy
        url: http://loki.monitoring.svc.cluster.local:3100
        isDefault: false
```

```bash
kubectl apply -f ci/monitoring/grafana-datasource-loki.yaml
```

Альтернатива — добавить datasource руками: **Connections → Data sources → Loki**,
URL тот же. Проверка: **Explore → Loki → Label browser**, должен появиться
`namespace` со значением `rtt`.

## 4. Запросы, которые пригодятся сразу

```logql
{namespace="rtt"}                                   # всё приложение
{namespace="rtt", app="rtt-worker"}                 # только celery
{namespace="rtt", level="ERROR"}                    # ошибки
{namespace="rtt"} |= "Поставлено на отслеживание"   # результат автопоиска
{namespace="rtt"} |= "Не удалось"                   # сбои задач

sum by (app) (count_over_time({namespace="rtt", level="ERROR"}[1h]))
```

Панель «ошибки за час по компонентам» делается из последнего запроса.

## 5. Логи приложения в JSON (желательно)

Сейчас формат текстовый (`app.py`), и уровень вытаскивается регуляркой.
JSON надёжнее: появятся поля `task`, `tour_id` и прочее, по которым можно
фильтровать в Grafana без перелопачивания текста.

```bash
uv add python-json-logger
```

`app.py`:

```python
from pythonjsonlogger.json import JsonFormatter

handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
```

Celery по умолчанию перехватывает корневой логгер и ломает такой формат,
поэтому в `src/celery/app.py` его нужно отключить:

```python
celery_app.conf.update(
    # остальные настройки без изменений
    worker_hijack_root_logger=False,
)
```

и настроить логирование так же, как в `app.py` (например, по сигналу
`celery.signals.setup_logging`).

После этого в Alloy `stage.regex` + `stage.labels` заменяются на:

```alloy
stage.json {
  expressions = {
    level  = "levelname",
    logger = "name",
  }
}
stage.labels {
  values = {
    level = "level",
  }
}
```

**Метками (labels) делать только малокардинальные поля** — `namespace`, `app`,
`container`, `level`. `tour_id`, `player_id`, текст сообщения в метки не класть:
Loki заводит отдельный поток на каждое сочетание меток и захлёбывается. Фильтр
по ним делается на лету: `{app="rtt-worker"} | json | tour_id="307095"`.

## 6. Сколько это стоит по ресурсам

| Компонент | RAM | Диск |
|---|---|---|
| Loki | 256–512 Mi | PVC 10 Gi, хватает на ~30 дней логов этого приложения |
| Alloy | 100–200 Mi на ноду | — |

Срок хранения правится в `limits_config.retention_period`; чистку делает
compactor, он включён в значениях выше.

## Что можно добавить дальше

- **Метрики приложения в Prometheus**: `prometheus-fastapi-instrumentator`
  отдаёт `/metrics` у API, плюс `ServiceMonitor` на сервис `rtt-api`.
  Для celery — экспортер `danihodovic/celery-exporter`.
- **Алерты по логам**: ruler в Loki умеет слать в тот же Alertmanager,
  что и Prometheus, — например, на `|= "Не удалось заполнить турнир"`.
- **Один чарт вместо двух**: `grafana/k8s-monitoring` ставит и настраивает
  Alloy под логи и метрики сам, но меньше контроля над конфигом.
