#!/bin/bash
set -e

STACK_NAME="b2b-pilot-local"
REGION="us-east-1"
BUCKET_NAME="test-bucket"

# 1️⃣ Start LocalStack if not already running
if [ "$(docker ps -q -f name=localstack)" == "" ]; then
  echo "Starting LocalStack..."
  docker compose up -d
fi

# 2️⃣ Wait for required services to be available
echo "Waiting for LocalStack services to be ready..."
while true; do
    HEALTH=$(curl -s http://localhost:4566/_localstack/health 2>/dev/null)

    LAMBDA=$(echo "$HEALTH" | jq -r '.services.lambda' 2>/dev/null)
    S3=$(echo "$HEALTH" | jq -r '.services.s3' 2>/dev/null)
    SQS=$(echo "$HEALTH" | jq -r '.services.sqs' 2>/dev/null)
    APIGW=$(echo "$HEALTH" | jq -r '.services.apigateway' 2>/dev/null)
    CF=$(echo "$HEALTH" | jq -r '.services.cloudformation' 2>/dev/null)

    echo "Lambda=$LAMBDA | S3=$S3 | SQS=$SQS | APIGW=$APIGW | CF=$CF"

    if [[ "$LAMBDA" == "available" || "$LAMBDA" == "running" ]] && \
       ([[ "$S3" == "available" ]] || [[ "$S3" == "running" ]]) && \
       [[ "$SQS" == "available" || "$SQS" == "running" ]] && \
       [[ "$APIGW" == "available" || "$APIGW" == "running" ]] && \
       [[ "$CF" == "available" || "$CF" == "running" ]]; then
        break
    fi
    sleep 2
done
echo "✅ All required services are available!"

# 3️⃣ Build SAM project
echo "Building SAM project..."
sam build

# 4️⃣ Delete existing stack if it exists
# if awslocal cloudformation describe-stacks --stack-name "$STACK_NAME" > /dev/null 2>&1; then
#     echo "Deleting existing stack $STACK_NAME..."
#     awslocal cloudformation delete-stack --stack-name "$STACK_NAME"

#     # wait for deletion to finish
#     while awslocal cloudformation describe-stacks --stack-name "$STACK_NAME" > /dev/null 2>&1; do
#         echo "Waiting for stack deletion..."
#         sleep 2
#     done
#     echo "✅ Previous stack deleted."
# fi

# 5️⃣ Create S3 bucket if it doesn't exist
if ! awslocal s3 ls "s3://$BUCKET_NAME" > /dev/null 2>&1; then
    echo "Creating S3 bucket $BUCKET_NAME..."
    awslocal s3 mb "s3://$BUCKET_NAME"
fi

# 6️⃣ Package SAM application (upload code to S3)
echo "Packaging SAM application..."
AWS_ACCESS_KEY_ID=test AWS_SECRET_ACCESS_KEY=test AWS_ENDPOINT_URL=http://localhost:4566 \
sam package \
  --template-file .aws-sam/build/template.yaml \
  --output-template-file .aws-sam/build/packaged-template.yaml \
  --s3-bucket "$BUCKET_NAME" \
  --s3-prefix lambda-code \
  --region "$REGION"

# 7️⃣ Deploy SAM stack
echo "Deploying SAM stack..."
aws cloudformation deploy \
  --template-file .aws-sam/build/packaged-template.yaml \
  --stack-name "$STACK_NAME" \
  --capabilities CAPABILITY_IAM \
  --region "$REGION" \
  --endpoint-url http://localhost:4566 \
  --parameter-overrides \
    Environment=staging \
    S3BucketName="$BUCKET_NAME" \
    TwilioAccountSid=dummy \
    TwilioAuthToken=dummy \
    TwilioPhoneNumber=whatsapp:+1234567890 \
    ResponseFeedbackTemplate="test" \
    SupabaseUrl="http://dummy" \
    SupabaseKey="dummy" \
    AiApiKey="dummy" \
    VirusTotalApiKey="dummy" \
    GoogleSafeBrowsingKey="dummy" \
    ApiKey="dummy"


# 8️⃣ List deployed resources
echo "✅ Deployed Lambda functions:"
awslocal lambda list-functions

echo "✅ SQS queues:"
awslocal sqs list-queues

echo "✅ API Gateway endpoints:"
awslocal apigateway get-rest-apis

echo ""
echo "✅ Stack outputs:"
aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --endpoint-url http://localhost:4566 \
  --query 'Stacks[0].Outputs' \
  --output table
