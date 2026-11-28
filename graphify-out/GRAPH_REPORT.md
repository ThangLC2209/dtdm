# Graph Report - dtdm  (2026-11-28)

## Corpus Check
- Corpus is ~11,406 words - fits in a single context window. You may not need a graph.

## Summary
- 312 nodes · 572 edges · 16 communities (8 shown, 8 thin omitted)
- Extraction: 93% EXTRACTED · 7% INFERRED · 0% AMBIGUOUS · INFERRED: 39 edges (avg confidence: 0.83)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- Xác thực và đăng nhập
- Azure Blob Storage
- Quy trình phê duyệt
- Kiểm thử và fixture
- Cấu hình và khởi tạo app
- Tài liệu dự án và kế hoạch
- Giao diện template
- GCP Firestore backend
- Azure SQL backend
- Local backend
- Local publisher và storage
- Script deploy GCP
- Script cleanup
- Quy tắc thuật ngữ

## God Nodes (most connected - your core abstractions)
1. `AzureSQLRepo` - 17 edges
2. `svc()` - 17 edges
3. `Browser` - 17 edges
4. `LocalRepo` - 16 edges
5. `FirestoreRepo` - 15 edges
6. `build_services()` - 15 edges
7. `decide()` - 14 edges
8. `create_app()` - 13 edges
9. `log()` - 13 edges
10. `make_doc()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `Quy tắc dùng tiếng Việt` --conceptually_related_to--> `Khung trang base.html`  [INFERRED]
  CLAUDE.md → app/templates/base.html
- `app()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_app.py → app/__init__.py
- `test_pubsub_push_is_idempotent()` --calls--> `create_app()`  [EXTRACTED]
  tests/test_app.py → app/__init__.py
- `Nút đăng nhập Microsoft` --implements--> `Microsoft Entra ID OIDC`  [INFERRED]
  app/templates/login.html → IMPLEMENTATION_PLAN.md
- `Chọn tài khoản demo` --conceptually_related_to--> `Chạy local`  [INFERRED]
  app/templates/login.html → README.md

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **Ngăn xếp Azure SDK dùng managed identity** — readme_azure_services_setup, requirements_azure_identity, requirements_azure_storage_blob, requirements_azure_servicebus [INFERRED 0.75]
- **Các màn hình dùng chung từ điển nhãn ROLES, STATUS_LABELS, ACTION_LABELS** — app_templates_audit_action_log, app_templates_detail_history_timeline, app_templates_users_role_management, app_templates__macros_doc_table [INFERRED 0.75]
- **Luồng đăng nhập Microsoft Entra ID** — implementation_plan_entra_oidc, app_templates_login_entra_button, readme_entra_app_registration, readme_azure_config_variables [INFERRED 0.75]

## Communities (16 total, 8 thin omitted)

### Community 0 - "Xác thực và đăng nhập"
Cohesion: 0.08
Nodes (35): login_required(), wrapper(), resolve_user(), roles_required(), decorator(), audit_log(), before_request(), create_document() (+27 more)

### Community 1 - "Azure Blob Storage"
Cohesion: 0.07
Nodes (9): AzureBlobStorage, AzureServiceBusPublisher, GcsStorage, PubSubPublisher, build_services(), Services, handle_event(), message_for() (+1 more)

### Community 2 - "Quy trình phê duyệt"
Cohesion: 0.12
Nodes (23): change(), _audit(), can_decide(), can_resubmit(), can_view(), decide(), _event(), initial_status() (+15 more)

### Community 3 - "Kiểm thử và fixture"
Cohesion: 0.13
Nodes (17): app(), Browser, doc_id_of(), envelope(), repo(), test_a_decided_document_cannot_be_decided_twice(), test_access_control(), test_admin_can_change_roles() (+9 more)

### Community 4 - "Cấu hình và khởi tạo app"
Cohesion: 0.13
Nodes (9): load_config(), create_app(), format_money(), format_size(), format_time(), main(), make_pdf(), Session (+1 more)

### Community 5 - "Tài liệu dự án và kế hoạch"
Cohesion: 0.11
Nodes (24): Chọn tài khoản demo, Quy tắc dùng tiếng Việt, Bảo toàn nghiệp vụ hiện có, Backend Azure (SQL, Blob, Service Bus), Hướng dẫn triển khai Azure, Kiểm thử local và tập trung, Tạo dịch vụ Azure, Chứng từ số (ứng dụng Flask) (+16 more)

### Community 6 - "Giao diện template"
Cohesion: 0.12
Nodes (22): Macro doc_table, Macro status_badge, Nhật ký thao tác, Khung trang base.html, Điều hướng chính theo vai trò, Đang chờ bạn duyệt, Tổng quan và thống kê trạng thái, Quyết định duyệt hoặc từ chối (+14 more)

### Community 11 - "Script deploy GCP"
Cohesion: 0.67
Nodes (5): bind_project(), create_sa(), exists(), deploy.sh script, step()

## Knowledge Gaps
- **15 isolated node(s):** `Thuật ngữ kỹ thuật giữ bằng tiếng Anh`, `Bảo toàn nghiệp vụ hiện có`, `Giao diện đăng nhập và khung trang`, `Hướng dẫn triển khai Azure`, `Kiểm thử local và tập trung` (+10 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 113 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `build_services()` connect `Azure Blob Storage` to `Xác thực và đăng nhập`, `Cấu hình và khởi tạo app`, `GCP Firestore backend`, `Azure SQL backend`, `Local backend`, `Local publisher và storage`?**
  _High betweenness centrality (0.209) - this node is a cross-community bridge._
- **What connects `Thuật ngữ kỹ thuật giữ bằng tiếng Anh`, `Bảo toàn nghiệp vụ hiện có`, `Giao diện đăng nhập và khung trang` to the rest of the system?**
  _15 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Xác thực và đăng nhập` be split into smaller, more focused modules?**
  _Cohesion score 0.08145363408521303 - nodes in this community are weakly interconnected._
- **Why does `FirestoreRepo` connect `GCP Firestore backend` to `Azure Blob Storage`?**
  _High betweenness centrality (0.087) - this node is a cross-community bridge._
- **Should `Azure Blob Storage` be split into smaller, more focused modules?**
  _Cohesion score 0.06747638326585695 - nodes in this community are weakly interconnected._
- **Why does `LocalRepo` connect `Local backend` to `Azure Blob Storage`, `Local publisher và storage`?**
  _High betweenness centrality (0.077) - this node is a cross-community bridge._
- **Should `Quy trình phê duyệt` be split into smaller, more focused modules?**
  _Cohesion score 0.11861861861861862 - nodes in this community are weakly interconnected._