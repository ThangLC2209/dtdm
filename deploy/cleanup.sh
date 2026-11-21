#!/usr/bin/env bash
# Gỡ toàn bộ tài nguyên của bản demo để không phát sinh chi phí sau buổi bảo vệ.
#
#   PROJECT_ID=ten-project-cua-ban ./deploy/cleanup.sh
#
# CẢNH BÁO: lệnh xóa bucket sẽ xóa vĩnh viễn mọi tệp chứng từ đã tải lên.
# Cơ sở dữ liệu Firestore được giữ lại; xóa trong Console nếu không cần nữa.
set -uo pipefail

PROJECT_ID="${PROJECT_ID:?Hãy đặt biến PROJECT_ID}"
REGION="${REGION:-asia-southeast1}"
BUCKET="${BUCKET:-${PROJECT_ID}-chungtu}"

read -r -p "Xóa tài nguyên demo trong project ${PROJECT_ID} (gồm bucket gs://${BUCKET})? [y/N] " answer
[[ "$answer" == "y" || "$answer" == "Y" ]] || { echo "Đã hủy."; exit 0; }

gcloud config set project "$PROJECT_ID" >/dev/null
gcloud pubsub subscriptions delete chungtu-events-push --quiet
gcloud pubsub topics delete chungtu-events --quiet
gcloud run services delete chungtu-web --region="$REGION" --quiet
gcloud run services delete chungtu-worker --region="$REGION" --quiet
gcloud artifacts repositories delete chungtu --location="$REGION" --quiet
gcloud secrets delete chungtu-secret-key --quiet
gcloud storage rm --recursive "gs://${BUCKET}"
for name in chungtu-web chungtu-worker chungtu-pubsub; do
  gcloud iam service-accounts delete "${name}@${PROJECT_ID}.iam.gserviceaccount.com" --quiet
done
echo "Đã gỡ xong."
