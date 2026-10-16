# Развёртывание в k3s

```
ci/rabbitmq/    брокер (StatefulSet + PVC)
ci/app/         приложение: миграции, api, worker, beat
ci/monitoring/  логи приложения: Loki + Alloy + Grafana
```

База и брокер считаются внешней инфраструктурой: `ci/app` только обращается
к ним по адресам из ConfigMap `rtt-config`.

## Что нужно создать один раз, до первой выкатки

```bash
kubectl create namespace rtt

# пароль базы (хост, имя БД и пользователь — в ConfigMap rtt-config)
kubectl -n rtt create secret generic rtt-secrets \
  --from-literal=APP_DB_PASSWORD='<пароль>'

# учётные данные брокера; приложение читает тот же секрет, что и сам RabbitMQ
kubectl -n rtt create secret generic rabbitmq \
  --from-literal=username='<логин>' \
  --from-literal=password='<пароль>'
```

Если брокер поднят манифестами из `ci/rabbitmq`, секрет `rabbitmq` уже есть —
замените в нём тестовые значения.

Адреса базы и брокера правятся в `ci/app/10-configmap.yaml`.

## Ручная выкатка

```bash
kustomize edit set image rtt-monitoring=ghcr.io/<owner>/<repo>:<tag>  # в ci/app
kubectl -n rtt delete job rtt-migrate --ignore-not-found
kubectl apply -k ci/app
kubectl -n rtt wait --for=condition=complete job/rtt-migrate --timeout=300s
kubectl -n rtt rollout status deployment/rtt-api
```

Обычно этого делать не нужно — то же самое выполняет workflow `CD`.

## Что настроить в GitHub

| Секрет / переменная | Назначение |
|---|---|
| `KUBE_CONFIG` | kubeconfig кластера в base64: `base64 -i ~/.kube/k3s.yaml \| pbcopy` |
| `WG_CONFIG` | конфиг WireGuard-пира для раннера, в base64 |
| `KUBE_API` | адрес API кластера в сети WG, например `10.8.0.10:6443` |
| Environment `production` | можно включить ручное подтверждение выкатки |

Образ публикуется в GHCR под именем репозитория, отдельный токен не нужен —
хватает `GITHUB_TOKEN` с правом `packages: write`.

## Доступ к закрытому кластеру через WireGuard

Кластер не виден из интернета, поэтому раннер GitHub сам поднимается пиром
в сеть WG и уже оттуда ходит в API кластера.

### На сервере с WireGuard

Завести пир для CI (ключи генерируются локально, в git не попадают):

```bash
wg genkey | tee runner.key | wg pubkey > runner.pub

# добавить пир на работающем интерфейсе — применяется сразу
sudo wg set wg0 peer "$(cat runner.pub)" allowed-ips 10.8.0.50/32

# и дописать его в конфиг, чтобы пережил перезапуск
sudo tee -a /etc/wireguard/wg0.conf > /dev/null <<EOF

[Peer]
# github actions runner
PublicKey = $(cat runner.pub)
AllowedIPs = 10.8.0.50/32
EOF

sudo wg show wg0   # пир должен быть в списке
```

Если привычнее перечитывать конфиг целиком, команду нужно выполнять
полностью от root — иначе `wg-quick strip` внутри подстановки запускается
от обычного пользователя и падает:

```bash
sudo bash -c 'wg syncconf wg0 <(wg-quick strip wg0)'
```

Раннер подключается сам, поэтому `Endpoint` для этого пира на сервере не нужен.
Убедитесь, что с адреса пира маршрутизируется сеть кластера
(`net.ipv4.ip_forward=1` и правила forward/NAT на сервере).

### Секрет `WG_CONFIG`

```ini
[Interface]
PrivateKey = <содержимое runner.key>
Address = 10.8.0.50/32

[Peer]
PublicKey = <публичный ключ сервера>
Endpoint = <внешний адрес сервера>:51820
# адреса, которые ходят через туннель: сеть WG и подсеть кластера
AllowedIPs = 10.8.0.0/24, 10.42.0.0/16
PersistentKeepalive = 25
```

```bash
base64 -i wg0.conf | pbcopy   # → секрет WG_CONFIG
```

В `KUBE_CONFIG` адрес сервера должен быть тем, который виден в сети WG
(`server: https://10.8.0.2:6443`), а не `127.0.0.1`.

### Сертификат API должен знать WG-адрес

По умолчанию сертификат k3s выписан на адреса ноды в её локальной сети.
При обращении по WG-адресу `kubectl` падает так:

```
tls: failed to verify certificate: x509: certificate is valid for
10.43.0.1, 127.0.0.1, 192.168.1.132, ::1, not 10.8.0.2
```

Лечится добавлением WG-адреса в SAN на ноде k3s:

```bash
# /etc/rancher/k3s/config.yaml
tls-san:
  - 10.8.0.2

sudo systemctl restart k3s
```

k3s перевыпускает сертификат при изменении списка SAN. Если адрес в сертификате
не появился, удалите серверный сертификат и перезапустите ещё раз — он создастся
заново:

```bash
sudo rm /var/lib/rancher/k3s/server/tls/serving-kube-apiserver.crt \
        /var/lib/rancher/k3s/server/tls/serving-kube-apiserver.key
sudo systemctl restart k3s
```

Проверка:

```bash
openssl s_client -connect 10.8.0.2:6443 </dev/null 2>/dev/null \
  | openssl x509 -noout -text | grep -A1 "Subject Alternative Name"
```

CA при этом не меняется, поэтому секрет `KUBE_CONFIG` переделывать не нужно.
Перезапуск k3s ненадолго гасит только API — поды продолжают работать.

### Альтернатива: self-hosted runner

Если не хочется пускать CI в VPN, поставьте раннер на машину внутри сети
(сервер WG или нода кластера) — он сам ходит к GitHub наружу, входящие
соединения не нужны. Тогда в `cd.yml` у job `deploy`:

- `runs-on: self-hosted` вместо `ubuntu-latest`;
- шаги «Подключиться к сети WireGuard», «Проверить, что API кластера виден»
  и «Отключиться от WireGuard» удалить.

Job `build` при этом остаётся на `ubuntu-latest`.

## Доступ к API снаружи

Сервис `rtt-api` имеет тип ClusterIP. Через встроенный в k3s traefik:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: rtt-api
  namespace: rtt
spec:
  rules:
    - host: <ваш-домен>
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: rtt-api
                port:
                  number: 80
```

Без домена — `kubectl -n rtt port-forward svc/rtt-api 8000:80`.
