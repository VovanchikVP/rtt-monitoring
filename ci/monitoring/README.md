# Логи приложения в Grafana

Prometheus хранит метрики и логи хранить не умеет — для логов нужен отдельный
стек. Минимальный набор поверх того, что уже есть в кластере:

| Компонент | Роль | Куда ставится |
|---|---|---|
| **Loki** | хранилище логов, аналог Prometheus для текста | `monitoring`, один под |
| **Grafana Alloy** | сборщик: читает логи подов с ноды и шлёт в Loki | `monitoring`, DaemonSet |
| **Grafana** | просмотр | `monitoring`, манифесты в этом каталоге |

```
поды rtt ──логи на диск ноды──▶ /var/log/pods ──▶ Alloy (DaemonSet)
                                                    │ push
                                                    ▼
                              Grafana ◀──запросы── Loki (PVC)
```

```
ci/monitoring/
  00-namespace.yaml   namespace monitoring
  loki/               хранилище логов: конфиг, сервис, StatefulSet + PVC
  alloy/              сборщик: RBAC, конфиг, DaemonSet
  grafana/            просмотр: секрет, datasource'ы, сервис, PV/PVC, Deployment
```

Всё ставится одной командой, порядок kustomize разберёт сам:

```bash
kubectl apply -k ci/monitoring
```

Компоненты независимы — `kubectl apply -k ci/monitoring/loki` и так далее
тоже работает, если namespace уже есть.

> **Promtail не использовать.** С 2 марта 2026 он EOL, сбор логов переехал
> в Grafana Alloy. Чарт `grafana/promtail` ещё лежит в репозитории, но новые
> установки делать на нём не нужно.

## 0. Проверить, что уже есть

```bash
kubectl get pods -A | grep -iE "grafana|prometheus|loki|alloy"
```

В кластере стоит `kube-prometheus-stack` (чарт раскатывается k3s-ным
`HelmChart` из `kube-system`), но **с выключенной Grafana** — в `monitoring`
живут только оператор, Prometheus, kube-state-metrics и node-exporter:

```bash
kubectl -n kube-system get helmchart kube-prometheus-stack \
  -o jsonpath='{.spec.valuesContent}'
```

Поэтому Grafana поднимается отдельно, манифестами из этого каталога (раздел 3),
и сама подключает к себе и Loki, и Prometheus от стека. Если когда-нибудь
включите Grafana в чарте — свою нужно будет снести, иначе в namespace окажутся
две.

Дальше по тексту namespace считается `monitoring`, поправьте под свой.

## 1. Loki

```
ci/monitoring/loki/
  10-configmap.yaml     конфиг Loki
  20-service.yaml       ClusterIP loki:3100 (http) и :9096 (grpc)
  30-statefulset.yaml   один под + PVC на 10 Gi
```

Настройки чарта по умолчанию рассчитаны на объектное хранилище и кластер
из многих нод. Здесь вместо этого монолитный режим (`-target=all`): все роли
в одном процессе, чанки и индекс на диске, кольцо в памяти, один арендатор.
Отдельные read/write/backend, memcached-кеши, gateway и canary не нужны —
на одной ноде они только едят память.

Что стоит знать про конфиг:

| Настройка | Зачем |
|---|---|
| `auth_enabled: false` | один арендатор, Grafana и Alloy ходят без `X-Scope-OrgID` |
| `limits_config.retention_period: 168h` | 7 дней; чистит compactor, он включён |
| `limits_config.max_query_lookback: 168h` | не пускать запросы за пределы срока хранения |
| `limits_config.volume_enabled: true` | иначе в Grafana не работает панель Logs volume |
| `ingestion_rate_mb: 8` | запас на всплески логов воркера, по умолчанию 4 |
| `query_range.results_cache` | кеш внутри процесса вместо отдельного memcached |
| `analytics.reporting_enabled: false` | кластер закрытый, наружу ходить незачем |

```bash
kubectl apply -k ci/monitoring/loki
kubectl -n monitoring rollout status statefulset/loki
```

Том — обычный `local-path` на 10 Gi, при сроке хранения 7 дней запас
многократный. Если логов станет больше, Loki разумно переселить на тот же SSD
по образцу `grafana/40-pv.yaml`: завести PV на `/data/loki` и заменить
`volumeClaimTemplates` на готовый PVC.

Адрес для datasource и для Alloy — `http://loki.monitoring.svc.cluster.local:3100`.

После правки конфига под нужно перекатить — StatefulSet сам изменений
в ConfigMap не видит:

```bash
kubectl -n monitoring rollout restart statefulset/loki
```

Проверка без Grafany:

```bash
kubectl -n monitoring port-forward svc/loki 3100:3100
curl -s 'http://localhost:3100/loki/api/v1/labels'
```

> **Promtail не использовать.** С 2 марта 2026 он EOL, сбор логов переехал
> в Grafana Alloy.

## 2. Alloy — сбор логов

```
ci/monitoring/alloy/
  10-rbac.yaml       ServiceAccount + ClusterRole на чтение подов
  20-configmap.yaml  config.alloy: что собирать и куда слать
  30-daemonset.yaml  по поду на каждую ноду
```

```bash
kubectl apply -k ci/monitoring/alloy
kubectl -n monitoring rollout status daemonset/alloy
kubectl -n monitoring logs ds/alloy | tail -20
```

Строки разбираются двумя регулярками подряд: формат `app.py`
(`2026-10-16 07:12:03,123 INFO src.module: текст`) и формат celery
(`[2026-10-16 07:12:03,123: INFO/ForkPoolWorker-1] текст`) — воркер логирует
по-своему, потому что celery перехватывает корневой логгер. Стадия, которая
не совпала, просто ничего не извлекает. Access-лог uvicorn
(`INFO:     10.42.0.1:51000 - "GET /tours HTTP/1.1" 200 OK`) не подходит
ни под одну, и метки `level` у таких строк нет — это учтено в дашборде.

Как это работает: `discovery.kubernetes` берёт список подов из API,
`discovery.relabel` превращает каждый под в путь к файлу логов на ноде
(`/var/log/pods/*<uid>/<container>/*.log`) и проставляет метки,
`loki.source.file` читает файлы, `loki.process` разбирает строки,
`loki.write` шлёт в Loki.

Поды ищутся по всему кластеру, а файлы есть только для локальных — цели
с чужих нод просто не находятся, фильтровать по ноде не нужно. Чтобы собирать
логи только приложения, в `20-configmap.yaml` есть закомментированное правило
`keep` по namespace `rtt`.

Детали DaemonSet'а:

- `runAsUser: 0` — файлы в `/var/log/pods` принадлежат root и читаются только им;
- `/var/log` монтируется с ноды только на чтение;
- `/var/lib/alloy` — hostPath, а не emptyDir: там лежат позиции чтения,
  и после перезапуска пода логи дочитываются с места остановки, а не с начала;
- `tolerations: Exists` — если на ноде k3s-сервера появятся тейнты,
  сбор логов с неё не пропадёт.

UI Alloy с графом компонентов и их состоянием:
`kubectl -n monitoring port-forward ds/alloy 12345:12345` → http://localhost:12345.

Правки конфига проверяются до выкатки, кластер для этого не нужен:

```bash
docker run --rm -v "$PWD":/w grafana/alloy:v1.20.1 validate /w/config.alloy
```

(файл `config.alloy` предварительно вынуть из ConfigMap в отдельный файл.)

## 3. Grafana

```
ci/monitoring/grafana/
  10-secret.yaml       логин/пароль администратора (значения тестовые)
  20-configmap.yaml    datasource'ы Loki и Prometheus, provisioning при старте
  30-service.yaml      ClusterIP grafana:80 → 3000
  40-pv.yaml           том на SSD ноды 192.168.1.132, /data/grafana
  50-pvc.yaml          заявка под SQLite-базу (дашборды, пользователи)
  60-deployment.yaml   сама Grafana
  70-dashboards-provider.yaml  откуда Grafana берёт дашборды
  80-dashboard-rtt.yaml        дашборд приложения, JSON целиком
```

### Диск

У Grafany свой том — SSD, смонтированный в `/data/grafana` на ноде
`192.168.1.132`. `local-path` в кластере остаётся как был, этот PV заведён
руками и провиженера не касается: `storageClassName: ""` и в PV, и в заявке
отключает динамическую выдачу, а `volumeName` + `claimRef` связывают их
напрямую, так что посторонний PVC том не перехватит.

Перед первой выкаткой подготовить каталог **на этой ноде**:

```bash
sudo mkdir -p /data/grafana
sudo chown 472:472 /data/grafana   # uid 472 — пользователь grafana в образе
sudo chmod 2775 /data/grafana      # setgid+g+rwx: kubelet не полезет chown'ить рекурсивно
```

И подставить в `grafana/40-pv.yaml` имя ноды: `nodeAffinity` сопоставляется
по `kubernetes.io/hostname`, адрес там не подойдёт.

```bash
kubectl get nodes -o wide          # нужна строка с INTERNAL-IP 192.168.1.132
```

Привязка к ноде жёсткая: под Grafana запустится только там, и если нода
недоступна, он останется в `Pending` — для одной реплики с локальным диском
это неизбежно.

`reclaimPolicy: Retain` — удаление PVC данные не трогает, PV остаётся
в `Released` и новой заявке не отдаётся. Чтобы переиспользовать том,
нужно снять с него ссылку на старую заявку:

```bash
kubectl patch pv grafana-data -p '{"spec":{"claimRef":null}}'
```

### Выкатка

Перед ней поменяйте пароль в `grafana/10-secret.yaml` (или заведите секрет
`grafana-admin` руками и уберите файл из `grafana/kustomization.yaml`):

```bash
kubectl apply -k ci/monitoring/grafana
kubectl get pv grafana-data                          # Bound
kubectl -n monitoring rollout status deployment/grafana
```

Вход: `kubectl -n monitoring port-forward svc/grafana 3000:80`, дальше
http://localhost:3000 и учётные данные из секрета.

Datasource заводится provisioning'ом — Grafana читает
`/etc/grafana/provisioning/datasources` при старте, руками в UI ничего
добавлять не нужно. После правки `grafana/20-configmap.yaml` поду нужен перезапуск:

```bash
kubectl -n monitoring rollout restart deployment/grafana
```

Тот же ConfigMap помечен `grafana_datasource: "1"`, поэтому если в чарте
включат Grafana, её sidecar подхватит datasource'ы сам — свою Grafana тогда
можно удалить.

Проверка: **Explore → Loki → Label browser**, должен появиться `namespace`
со значением `rtt`; **Explore → Prometheus** — метрики ноды и kube-state-metrics.

Дашборд приложения приезжает provisioning'ом, см. ниже. Готовых дашбордов по
кластеру у этой Grafany нет: они идут в subchart'е, который выключен. Нужные
берутся из **Dashboards → New → Import** по ID с grafana.com (1860 — Node
Exporter Full, 15757 — Kubernetes / Views / Pods), для этого Grafane нужен
доступ в интернет; либо импортом JSON-файла руками.

### Дашборд приложения

`80-dashboard-rtt.yaml` — дашборд **RTT monitoring** в папке `RTT`, окно по
умолчанию — сутки, обновление раз в минуту. Все панели считаются по логам:
метрик у приложения пока нет, так что Prometheus здесь не участвует.

| Панель | Что считает |
|---|---|
| Задач celery выполнено | строки воркера `Task ...[id] succeeded in ...s` |
| Ошибок в задачах | строки воркера с `level="ERROR"` |
| Запросов к API | access-лог uvicorn **без** `/health` |
| Ответов 4xx/5xx | то же, с кодом ответа на 4 или 5 |
| Задачи celery по типам | те же успешные задачи, имя задачи из текста строки |
| Запросы к API без /health | разбивка по HTTP-методу |
| Запросы по путям и кодам ответа | таблица метод/путь/код за выбранный период |
| Ошибки по компонентам | `level="ERROR"` в разрезе `app` |
| Логи (ряд свёрнут) | два окна логов: API и worker |

`/health` отсекается не по метке, а по самой строке запроса: его дёргает
kubelet каждые 10 секунд, и без фильтра он перебивает весь остальной трафик.
Запрос целиком:

```logql
sum(count_over_time({namespace="$namespace", app="rtt-api"}
  |~ `"[A-Z]+ [^"]+ HTTP/[0-9.]+"`
  !~ `"[A-Z]+ /health[^"]*"` [$__range]))
```

Первый фильтр оставляет только строки access-лога, второй выкидывает из них
пробы. Панели с разбивкой добавляют к этому `| regexp` с группами `method`,
`path`, `status`.

Переменные: `namespace` (подтягивается из меток Loki) и `поиск в логах` —
подстрока или regexp, который подставляется в обе панели логов.

Правки из UI не сохраняются (`allowUiUpdates: false`), источник правды — git.
Поиграться с панелями удобно через **Save as** — копия уже обычная.
Чтобы перенести правки обратно: **Dashboard settings → JSON Model**, скопировать
в `80-dashboard-rtt.yaml` (отступ 4 пробела) и применить. Пересоздавать под не
нужно, Grafana перечитывает каталог раз в минуту.

### Доступ снаружи

Через встроенный в k3s traefik, с правкой `GF_SERVER_ROOT_URL` в деплойменте
на тот же адрес:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: grafana
  namespace: monitoring
spec:
  rules:
    - host: <ваш-домен>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: grafana
                port:
                  number: 80
```

## 4. Запросы, которые пригодятся сразу

```logql
{namespace="rtt"}                                   # всё приложение
{namespace="rtt", app="rtt-worker"}                 # только celery
{namespace="rtt", level="ERROR"}                    # ошибки
{namespace="rtt"} |= "Поставлено на отслеживание"   # результат автопоиска
{namespace="rtt"} |= "Не удалось"                   # сбои задач

{namespace="rtt", app="rtt-worker"} |= "succeeded in"   # завершённые задачи

sum by (app) (count_over_time({namespace="rtt", level="ERROR"}[1h]))
```

Последний запрос — панель «Ошибки по компонентам» на дашборде RTT monitoring;
остальные панели собраны из таких же строчек, их видно в JSON Model.

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
| Loki | 256–512 Mi | PVC 10 Gi, при хранении 7 дней занято заметно меньше |
| Alloy | 100–200 Mi на ноду | — |
| Grafana | 128–512 Mi | 5 Gi на SSD ноды, реально занимает десятки мегабайт |

Срок хранения — 7 дней, правится в `limits_config.retention_period`
(`loki/10-configmap.yaml`) вместе с `max_query_lookback`; чистку делает
compactor, он включён.

## Что можно добавить дальше

- **Метрики приложения в Prometheus**: `prometheus-fastapi-instrumentator`
  отдаёт `/metrics` у API, плюс `ServiceMonitor` на сервис `rtt-api`.
  Для celery — экспортер `danihodovic/celery-exporter`.
- **Алерты по логам**: ruler в Loki умеет слать в тот же Alertmanager,
  что и Prometheus, — например, на `|= "Не удалось заполнить турнир"`.
- **Метрики самих Loki и Alloy**: оператор `kube-prometheus-stack` уже стоит,
  так что хватит `ServiceMonitor` на `loki:3100/metrics` и `alloy:12345/metrics`.
