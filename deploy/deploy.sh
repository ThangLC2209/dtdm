#!/usr/bin/env bash
# Triển khai bản demo "Chứng từ số" lên Google Cloud.
#
#   PROJECT_ID=ten-project-cua-ban ./deploy/deploy.sh
#
# Chạy từ thư mục gốc của mã nguồn, trong Cloud Shell hoặc máy đã cài gcloud và đã
# đăng nhập (gcloud auth login). Project phải được gắn tài khoản thanh toán.
# Chạy lại nhiều lần vẫn an toàn: tài nguyên đã có thì được giữ nguyên.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Hãy đặt biến PROJECT_ID, ví dụ: PROJECT_ID=my-project ./deploy/deploy.sh}"
REGION="${REGION:-asia-southeast1}"            # Singapore: vùng gần Việt Nam
BUCKET="${BUCKET:-${PROJECT_ID}-chungtu}"      # tên bucket phải duy nhất toàn cầu
AUTH_MODE="${AUTH_MODE:-demo}"
LEVEL2_THRESHOLD="${LEVEL2_THRESHOLD:-20000000}"

REPO="chungtu"
TOPIC="chungtu-events"
SUBSCRIPTION="chungtu-events-push"
SECRET="chungtu-secret-key"
WEB_SA="chungtu-web@${PROJECT_ID}.iam.gserviceaccount.com"
WORKER_SA="chungtu-worker@${PROJECT_ID}.iam.gserviceaccount.com"
PUSH_SA="chungtu-pubsub@${PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/app:$(date +%Y%m%d-%H%M%S)"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
exists() { "$@" >/dev/null 2>&1; }

gcloud config set project "$PROJECT_ID" >/dev/null

step "1/9 Bật các API cần dùng"
gcloud services enable \
  run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  firestore.googleapis.com storage.googleapis.com pubsub.googleapis.com \
  secretmanager.googleapis.com iamcredentials.googleapis.com

step "2/9 Firestore (chế độ Native) tại ${REGION}"
exists gcloud firestore databases describe --database="(default)" ||
  gcloud firestore databases create --database="(default)" --location="$REGION" \
    --type=firestore-native

step "3/9 Bucket Cloud Storage riêng tư, bật phiên bản và vòng đời lưu trữ"
exists gcloud storage buckets describe "gs://${BUCKET}" ||
  gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
    --uniform-bucket-level-access --public-access-prevention
gcloud storage buckets update "gs://${BUCKET}" --versioning \
  --lifecycle-file="$(dirname "$0")/lifecycle.json"

step "4/9 Service account riêng cho từng thành phần (quyền tối thiểu)"
create_sa() {
  exists gcloud iam service-accounts describe "$1@${PROJECT_ID}.iam.gserviceaccount.com" ||
    gcloud iam service-accounts create "$1" --display-name="$2"
}
create_sa chungtu-web "Chung tu - web"
create_sa chungtu-worker "Chung tu - worker"
create_sa chungtu-pubsub "Chung tu - Pub/Sub push"
sleep 10  # chờ service account mới lan truyền trước khi gán quyền

step "5/9 Pub/Sub topic và Secret Manager"
exists gcloud pubsub topics describe "$TOPIC" || gcloud pubsub topics create "$TOPIC"
exists gcloud secrets describe "$SECRET" ||
  python3 -c "import secrets; print(secrets.token_hex(32), end='')" |
    gcloud secrets create "$SECRET" --replication-policy=automatic --data-file=-

step "6/9 Gán quyền IAM"
bind_project() {
  gcloud projects add-iam-policy-binding "$PROJECT_ID" --member="serviceAccount:$1" \
    --role="$2" --condition=None >/dev/null
}
# Web: đọc/ghi Firestore, đọc/ghi đối tượng trong đúng bucket, phát tin vào đúng topic,
# đọc đúng secret, và tự ký URL (signBlob) bằng danh tính của chính nó.
bind_project "$WEB_SA" roles/datastore.user
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${WEB_SA}" --role=roles/storage.objectUser >/dev/null
gcloud pubsub topics add-iam-policy-binding "$TOPIC" \
  --member="serviceAccount:${WEB_SA}" --role=roles/pubsub.publisher >/dev/null
gcloud secrets add-iam-policy-binding "$SECRET" \
  --member="serviceAccount:${WEB_SA}" --role=roles/secretmanager.secretAccessor >/dev/null
gcloud iam service-accounts add-iam-policy-binding "$WEB_SA" \
  --member="serviceAccount:${WEB_SA}" --role=roles/iam.serviceAccountTokenCreator >/dev/null
# Worker: chỉ cần Firestore để ghi thông báo.
bind_project "$WORKER_SA" roles/datastore.user

step "7/9 Build image bằng Cloud Build, lưu vào Artifact Registry"
exists gcloud artifacts repositories describe "$REPO" --location="$REGION" ||
  gcloud artifacts repositories create "$REPO" --repository-format=docker \
    --location="$REGION" --description="Image cua he thong chung tu"
gcloud builds submit --tag "$IMAGE" .

step "8/9 Triển khai hai dịch vụ Cloud Run từ cùng một image"
COMMON_ENV="BACKEND=gcp,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},BUCKET=${BUCKET},PUBSUB_TOPIC=${TOPIC}"
gcloud run deploy chungtu-web --image="$IMAGE" --region="$REGION" \
  --service-account="$WEB_SA" --allow-unauthenticated \
  --set-env-vars="${COMMON_ENV},AUTH_MODE=${AUTH_MODE},LEVEL2_THRESHOLD=${LEVEL2_THRESHOLD}" \
  --set-secrets="SECRET_KEY=${SECRET}:latest" \
  --memory=512Mi --cpu=1 --concurrency=40 --min-instances=0 --max-instances=3
gcloud run deploy chungtu-worker --image="$IMAGE" --region="$REGION" \
  --service-account="$WORKER_SA" --no-allow-unauthenticated \
  --set-env-vars="${COMMON_ENV},ENABLE_WORKER=1" \
  --memory=512Mi --cpu=1 --min-instances=0 --max-instances=2

step "9/9 Push subscription: Pub/Sub gọi worker kèm OIDC token"
WORKER_URL="$(gcloud run services describe chungtu-worker --region="$REGION" --format='value(status.url)')"
gcloud run services add-iam-policy-binding chungtu-worker --region="$REGION" \
  --member="serviceAccount:${PUSH_SA}" --role=roles/run.invoker >/dev/null
exists gcloud pubsub subscriptions describe "$SUBSCRIPTION" ||
  gcloud pubsub subscriptions create "$SUBSCRIPTION" --topic="$TOPIC" \
    --push-endpoint="${WORKER_URL}/internal/pubsub" \
    --push-auth-service-account="$PUSH_SA" \
    --ack-deadline=30 --min-retry-delay=10s --max-retry-delay=600s

WEB_URL="$(gcloud run services describe chungtu-web --region="$REGION" --format='value(status.url)')"
printf '\n\033[1;32mHoàn tất.\033[0m Mở ứng dụng tại: %s\n' "$WEB_URL"
