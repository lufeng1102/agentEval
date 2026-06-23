# P3 Phase 0：Hosted Mode 数据模型草案

## 1. MVP 边界

Hosted mode MVP 只托管：

- run artifacts
- report data
- dashboard read API
- CLI upload/sync
- export outputs
- alert metadata

不托管：

- 用户 agent runtime
- remote sandbox
- evaluator execution workers
- billing
- SSO

## 2. 实体关系

```text
Workspace
  -> Project
    -> Run
      -> RunArtifact
      -> CaseRecord
      -> EvalResultRecord
      -> TraceRecord
        -> SpanRecord
      -> ExportJob
      -> AlertEvent

Workspace
  -> User
  -> Membership
  -> ApiToken
  -> AuditLog
```

## 3. Workspace

```sql
create table workspaces (
  id text primary key,
  name text not null,
  slug text unique not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  metadata jsonb not null default '{}'
);
```

## 4. Project

```sql
create table projects (
  id text primary key,
  workspace_id text not null references workspaces(id),
  name text not null,
  slug text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null,
  metadata jsonb not null default '{}',
  unique(workspace_id, slug)
);
```

MVP local/default hosted 可自动创建：

```text
workspace=default
project=default
```

## 5. User / Membership

```sql
create table users (
  id text primary key,
  email text unique,
  display_name text,
  created_at timestamptz not null,
  updated_at timestamptz not null
);
```

```sql
create table memberships (
  id text primary key,
  workspace_id text not null references workspaces(id),
  user_id text not null references users(id),
  role text not null check (role in ('owner', 'admin', 'developer', 'eval_engineer', 'viewer')),
  created_at timestamptz not null,
  unique(workspace_id, user_id)
);
```

## 6. API Token

```sql
create table api_tokens (
  id text primary key,
  workspace_id text not null references workspaces(id),
  project_id text references projects(id),
  name text not null,
  token_hash text not null unique,
  role text not null,
  scopes jsonb not null default '[]',
  created_by text references users(id),
  created_at timestamptz not null,
  last_used_at timestamptz,
  revoked_at timestamptz
);
```

MVP scopes：

```text
runs:upload
runs:read
artifacts:read
exports:create
alerts:write
```

## 7. Run

```sql
create table runs (
  id text primary key,
  workspace_id text not null references workspaces(id),
  project_id text not null references projects(id),
  run_key text not null,
  idempotency_key text,
  status text not null check (status in ('uploading', 'uploaded', 'indexed', 'failed')),
  source text not null default 'cli_upload',
  created_at timestamptz not null,
  updated_at timestamptz not null,
  completed_at timestamptz,
  manifest jsonb not null default '{}',
  summary jsonb not null default '{}',
  agent_provider text,
  agent_model text,
  prompt_hash text,
  dataset_hash text,
  config_hash text,
  metadata jsonb not null default '{}',
  unique(project_id, run_key)
);
```

`run_key` 来源优先级：

1. manifest 中已有 run id。
2. CLI `--run-key`。
3. 本地目录名 + artifact hash。

`idempotency_key`：

```text
sha256(manifest.json + traces.jsonl + results.jsonl + report.json)
```

## 8. RunArtifact

```sql
create table run_artifacts (
  id text primary key,
  run_id text not null references runs(id),
  kind text not null check (kind in (
    'manifest',
    'traces_jsonl',
    'results_jsonl',
    'report_json',
    'report_md',
    'report_html',
    'environment_jsonl',
    'compare_json',
    'export_jsonl',
    'other'
  )),
  path text not null,
  content_type text not null,
  size_bytes bigint not null,
  sha256 text not null,
  storage_url text not null,
  created_at timestamptz not null,
  metadata jsonb not null default '{}',
  unique(run_id, kind, sha256)
);
```

## 9. CaseRecord

```sql
create table case_records (
  id text primary key,
  run_id text not null references runs(id),
  case_id text not null,
  repeat_index int not null default 0,
  name text,
  input jsonb,
  expected jsonb,
  tags jsonb not null default '[]',
  metadata jsonb not null default '{}',
  final_output text,
  latency_ms double precision,
  usage jsonb not null default '{}',
  errors jsonb not null default '[]',
  artifacts jsonb not null default '{}',
  status text not null,
  score double precision,
  created_at timestamptz not null,
  unique(run_id, case_id, repeat_index)
);
```

## 10. EvalResultRecord

```sql
create table eval_result_records (
  id text primary key,
  run_id text not null references runs(id),
  case_id text not null,
  repeat_index int not null default 0,
  evaluator text not null,
  score double precision not null,
  passed boolean not null,
  metrics jsonb not null default '{}',
  judgements jsonb not null default '[]',
  failure_reason text,
  failure_type text,
  artifacts jsonb not null default '{}',
  created_at timestamptz not null
);
```

## 11. TraceRecord / SpanRecord

```sql
create table trace_records (
  id text primary key,
  run_id text not null references runs(id),
  case_id text,
  repeat_index int not null default 0,
  trace_id text not null,
  source text,
  session_id text,
  agent_id text,
  agent_version text,
  final_output text,
  latency_ms double precision,
  usage jsonb not null default '{}',
  errors jsonb not null default '[]',
  metadata jsonb not null default '{}',
  created_at timestamptz not null,
  unique(run_id, trace_id)
);
```

```sql
create table span_records (
  id text primary key,
  trace_record_id text not null references trace_records(id),
  span_id text not null,
  parent_span_id text,
  name text not null,
  kind text not null,
  start_time timestamptz,
  end_time timestamptz,
  latency_ms double precision,
  status text,
  input jsonb,
  output jsonb,
  error text,
  attributes jsonb not null default '{}',
  events jsonb not null default '[]',
  unique(trace_record_id, span_id)
);
```

## 12. ExportJob

```sql
create table export_jobs (
  id text primary key,
  run_id text not null references runs(id),
  target text not null check (target in ('langfuse', 'phoenix', 'braintrust')),
  status text not null check (status in ('pending', 'running', 'succeeded', 'failed')),
  config jsonb not null default '{}',
  output_artifact_id text references run_artifacts(id),
  validation jsonb not null default '{}',
  error text,
  created_at timestamptz not null,
  started_at timestamptz,
  completed_at timestamptz
);
```

## 13. Alerts

```sql
create table alert_rules (
  id text primary key,
  project_id text not null references projects(id),
  name text not null,
  type text not null,
  enabled boolean not null default true,
  config jsonb not null,
  severity text not null,
  created_at timestamptz not null,
  updated_at timestamptz not null
);
```

```sql
create table alert_events (
  id text primary key,
  rule_id text references alert_rules(id),
  run_id text not null references runs(id),
  severity text not null,
  status text not null default 'open',
  summary text not null,
  payload jsonb not null,
  dedupe_key text,
  created_at timestamptz not null,
  resolved_at timestamptz
);
```

```sql
create table webhook_deliveries (
  id text primary key,
  alert_event_id text not null references alert_events(id),
  url text not null,
  status text not null,
  attempt int not null,
  request_body jsonb not null,
  response_status int,
  response_body text,
  error text,
  created_at timestamptz not null,
  delivered_at timestamptz
);
```

## 14. AuditLog

```sql
create table audit_logs (
  id text primary key,
  workspace_id text not null references workspaces(id),
  project_id text references projects(id),
  actor_user_id text references users(id),
  actor_token_id text references api_tokens(id),
  action text not null,
  resource_type text not null,
  resource_id text not null,
  ip_address text,
  user_agent text,
  metadata jsonb not null default '{}',
  created_at timestamptz not null
);
```

## 15. Ingestion API

### Multipart MVP

```http
POST /api/runs/upload
Authorization: Bearer <token>
Content-Type: multipart/form-data
```

Files：

```text
manifest.json
traces.jsonl
results.jsonl
report.json
report.md optional
report.html optional
```

Form：

```json
{
  "project_id": "proj_default",
  "run_key": "local-runs-latest",
  "idempotency_key": "sha256:..."
}
```

Response：

```json
{
  "run_id": "run_123",
  "status": "indexed",
  "already_exists": false,
  "dashboard_url": "https://.../runs/run_123"
}
```

## 16. Idempotency

- 相同 `project_id + run_key` 且 artifact sha256 完全相同：返回 existing run。
- 相同 `project_id + run_key` 但 artifact sha256 不同：返回 `409 conflict`，除非 `overwrite=true`。
- 相同 `idempotency_key`：返回同一 `run_id`。
- 上传中断：run status 保持 `uploading`，可重传缺失 artifact。

## 17. Hosted Dashboard API

```http
GET /api/projects/{project_id}/runs
GET /api/runs/{run_id}
GET /api/runs/{run_id}/cases
GET /api/runs/{run_id}/cases/{case_id}?repeat_index=0
GET /api/runs/{run_id}/cases/{case_id}/trace?repeat_index=0
GET /api/runs/{run_id}/results?case_id=case_001
GET /api/runs/{run_id}/artifacts
GET /api/runs/{run_id}/artifacts/{artifact_id}/download
POST /api/runs/{run_id}/exports
GET /api/runs/{run_id}/exports/{export_job_id}
```

## 18. 权限矩阵

| 操作 | Owner | Admin | Developer | Eval Engineer | Viewer |
|---|---|---|---|---|---|
| 上传 run | 是 | 是 | 是 | 是 | 否 |
| 查看 run/report | 是 | 是 | 是 | 是 | 是 |
| 下载 artifacts | 是 | 是 | 是 | 是 | 是 |
| 删除 run | 是 | 是 | 否 | 否 | 否 |
| 创建 token | 是 | 是 | 否 | 否 | 否 |
| 配置 alert | 是 | 是 | 否 | 是 | 否 |
| 创建 export | 是 | 是 | 是 | 是 | 否 |
| 管理成员 | 是 | 是 | 否 | 否 | 否 |

## 19. 验收标准

- multipart 上传 run 成功并返回 `run_id`。
- 同一 run 重复上传不创建重复数据。
- 同 `run_key` 不同 hash 返回 409。
- artifact download 的 sha256 与上传一致。
- 无 token 上传返回 401/403。
- viewer token 上传返回 403。
- upload/export/token 操作写 audit log。
