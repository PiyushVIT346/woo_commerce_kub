{{- define "platform.secretName" -}}{{ default "platform-secrets" .Values.existingSecret }}{{- end -}}

{{- define "platform.image" -}}{{ printf "%s%s:%s" .root.Values.images.registry .name .root.Values.images.tag }}{{- end -}}

{{/* secret value: explicit override > existing in cluster (stable across upgrades) > generated */}}
{{- define "platform.secret" -}}
{{- if .v }}{{ .v }}{{- else if and .d (hasKey .d .k) }}{{ index .d .k | b64dec }}{{- else if .gen }}{{ .p }}{{ randAlphaNum 40 }}{{- end }}
{{- end -}}

{{- define "platform.env" -}}
- name: {{ .name }}
  valueFrom:
    secretKeyRef:
      name: {{ include "platform.secretName" .root }}
      key: {{ .key }}
{{- end -}}

{{- define "platform.wpEnv" -}}
- name: WORDPRESS_DB_HOST
  value: mariadb
- name: WORDPRESS_DB_NAME
  value: wordpress
- name: WORDPRESS_DB_USER
  value: wordpress
{{ include "platform.env" (dict "root" . "name" "WORDPRESS_DB_PASSWORD" "key" "mariadb-password") }}
- name: WORDPRESS_CONFIG_EXTRA
  value: |
    define('WP_HOME', '{{ .Values.urls.shop }}');
    define('WP_SITEURL', '{{ .Values.urls.shop }}');
{{- end -}}

{{/* Generic Deployment + Service for the stateless apps */}}
{{- define "platform.app" -}}
{{- $r := .root -}}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .name }}
  labels:
    app.kubernetes.io/name: {{ .name }}
spec:
  replicas: {{ .replicas | default 1 }}
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ .name }}
  template:
    metadata:
      labels:
        app.kubernetes.io/name: {{ .name }}
        app.kubernetes.io/component: {{ .component }}
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: {{ .uid }}
      containers:
        - name: app
          image: {{ include "platform.image" (dict "root" $r "name" .image) }}
          imagePullPolicy: {{ $r.Values.images.pullPolicy }}
          ports:
            - containerPort: {{ .port }}
          env:
            {{- .env | nindent 12 }}
          readinessProbe:
            httpGet: { path: /healthz, port: {{ .port }} }
            initialDelaySeconds: 3
            periodSeconds: 5
          livenessProbe:
            httpGet: { path: /healthz, port: {{ .port }} }
            initialDelaySeconds: 40
            periodSeconds: 10
            failureThreshold: 6
          resources:
            {{- toYaml .resources | nindent 12 }}
---
apiVersion: v1
kind: Service
metadata:
  name: {{ .name }}
spec:
  selector:
    app.kubernetes.io/name: {{ .name }}
  ports:
    - port: {{ .port }}
      targetPort: {{ .port }}
{{- end -}}
