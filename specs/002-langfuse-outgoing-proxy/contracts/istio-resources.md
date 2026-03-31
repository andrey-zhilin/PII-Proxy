# Istio Resources Contract

**Branch**: `002-langfuse-outgoing-proxy` | **Date**: 2026-03-23

Defines the Istio networking resources rendered by `helm/pii-proxy/templates/istio-resources.yaml` when `istio.enabled: true`.

---

## ServiceEntry — `langfuse-external`

Registers the external Langfuse host in the Istio service registry. Required in clusters where `outboundTrafficPolicy: REGISTRY_ONLY` is enforced; harmless in permissive clusters.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: {{ include "pii-proxy.fullname" . }}-langfuse
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "pii-proxy.labels" . | nindent 4 }}
spec:
  hosts:
    - {{ .Values.langfuse.host | quote }}
  ports:
    - number: {{ .Values.langfuse.port }}
      name: {{ if .Values.langfuse.tls.enabled }}https{{ else }}http{{ end }}
      protocol: {{ if .Values.langfuse.tls.enabled }}HTTPS{{ else }}HTTP{{ end }}
  location: MESH_EXTERNAL
  resolution: DNS
```

**Constraints**:

- `spec.hosts[0]` MUST exactly match `langfuse.host` used in Envoy's upstream cluster configuration.
- `spec.resolution: DNS` requires the Langfuse hostname to be resolvable from inside the cluster.
- Only one port entry per ServiceEntry. If Langfuse is accessed on both 80 and 443, additional ports must be added.

---

## DestinationRule — `langfuse-external`

Tells Istio NOT to apply its own TLS when the PII proxy connects to Langfuse. Envoy's `UpstreamTlsContext` handles TLS origination directly; a second TLS layer from Istio would cause a handshake failure.

```yaml
apiVersion: networking.istio.io/v1beta1
kind: DestinationRule
metadata:
  name: {{ include "pii-proxy.fullname" . }}-langfuse
  namespace: {{ .Release.Namespace }}
  labels:
    {{- include "pii-proxy.labels" . | nindent 4 }}
spec:
  host: {{ .Values.langfuse.host | quote }}
  trafficPolicy:
    tls:
      mode: {{ if .Values.langfuse.tls.enabled }}DISABLE{{ else }}DISABLE{{ end }}
```

> **Note**: `tls.mode: DISABLE` is correct regardless of whether Langfuse uses TLS, because Envoy already manages the upstream TLS connection. Istio must not intercept or re-encrypt this traffic.

---

## Pod Annotations (injected by Deployment template)

When `istio.enabled: true`, the following annotations are added to the PII proxy pod template:

```yaml
annotations:
  traffic.sidecar.istio.io/excludeInboundPorts: "{{ .Values.envoy.httpsPort }}"
  traffic.sidecar.istio.io/excludeOutboundPorts: "{{ .Values.langfuse.port }}"
```

| Annotation | Effect |
|-----------|--------|
| `excludeInboundPorts: "443"` | Istio sidecar does NOT intercept inbound port 443. Envoy's HTTPS listener handles TLS termination directly. Without this, Istio would strip TLS before Envoy sees it. |
| `excludeOutboundPorts: "443"` | Istio sidecar does NOT intercept Envoy's outbound HTTPS connection to Langfuse. Prevents double-TLS. |

**These annotations are only rendered when `istio.enabled: true`** — they have no effect when Istio is absent and are omitted to keep the pod template clean in non-Istio deployments.

---

## Conditional Rendering

All resources in `istio-resources.yaml` are wrapped in:

```
{{- if .Values.istio.enabled }}
...resources...
{{- end }}
```

When `istio.enabled: false` (default), no Istio CRDs are created and no pod annotations are added. The chart can be deployed to a non-Istio cluster without errors.
