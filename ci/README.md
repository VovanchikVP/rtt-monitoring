# Развёртывание в k3s

```
ci/rabbitmq/  брокер (StatefulSet + PVC)
ci/app/       приложение: миграции, api, worker, beat
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
| Environment `production` | можно включить ручное подтверждение выкатки |

Образ публикуется в GHCR под именем репозитория, отдельный токен не нужен —
хватает `GITHUB_TOKEN` с правом `packages: write`.

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
