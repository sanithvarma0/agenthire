#!/usr/bin/env bash
# Create the AgentHire server on AWS (run once, from the laptop, with the AWS CLI signed in).
#
#   bash deploy/provision.sh
#
# Makes, in us-east-1 (see REGION below): an SSH key pair saved to ~/.ssh/agenthire.pem, a security
# group (SSH from this machine's IP only; HTTP and HTTPS from anywhere), one c7i.xlarge
# (4 vCPU, 8 GB, no GPU) running Ubuntu 24.04 with a 30 GB disk, and an Elastic IP so the
# address survives a stop and start. Prints the address and the site's HTTPS host name.
# Safe to run again: it reuses what already exists.
set -euo pipefail
# Git Bash on Windows rewrites arguments that start with "/" into Windows paths, which
# broke the image lookup ("/aws/service/..." became "C:/...").
export MSYS_NO_PATHCONV=1

# The event's AWS account (a workshop participant role) allows servers only in us-east-1
# and us-west-2; Mumbai, Hyderabad and Singapore are refused. us-east-1 is the closer of the
# two to India (LiveKit's India region, Sarvam) and to OpenAI.
REGION="${REGION:-us-east-1}"
TYPE="${INSTANCE_TYPE:-c7i.xlarge}"
NAME="agenthire"
KEY_FILE="$HOME/.ssh/agenthire.pem"
export AWS_DEFAULT_REGION="$REGION"

if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
  mkdir -p "$HOME/.ssh"
  aws ec2 create-key-pair --key-name "$NAME" --key-type ed25519 --query KeyMaterial --output text > "$KEY_FILE"
  chmod 600 "$KEY_FILE"
  echo "Key pair saved to $KEY_FILE"
fi

VPC=$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query "Vpcs[0].VpcId" --output text)
SG=$(aws ec2 describe-security-groups --filters Name=group-name,Values="$NAME" Name=vpc-id,Values="$VPC" \
     --query "SecurityGroups[0].GroupId" --output text)
if [ "$SG" = "None" ]; then
  SG=$(aws ec2 create-security-group --group-name "$NAME" --description "AgentHire web and SSH" \
       --vpc-id "$VPC" --query GroupId --output text)
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 80 --cidr 0.0.0.0/0 >/dev/null
  aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 443 --cidr 0.0.0.0/0 >/dev/null
fi
MYIP=$(curl -s https://checkip.amazonaws.com)
aws ec2 authorize-security-group-ingress --group-id "$SG" --protocol tcp --port 22 --cidr "$MYIP/32" >/dev/null 2>&1 || true

INSTANCE=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" \
           "Name=instance-state-name,Values=pending,running,stopping,stopped" \
           --query "Reservations[0].Instances[0].InstanceId" --output text)
if [ "$INSTANCE" = "None" ]; then
  AMI=$(aws ssm get-parameters --names /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
        --query "Parameters[0].Value" --output text)
  INSTANCE=$(aws ec2 run-instances --image-id "$AMI" --instance-type "$TYPE" --key-name "$NAME" \
             --security-group-ids "$SG" \
             --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":30,"VolumeType":"gp3"}}]' \
             --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
             --query "Instances[0].InstanceId" --output text)
  echo "Started $INSTANCE ($TYPE); waiting for it to run..."
fi
aws ec2 wait instance-running --instance-ids "$INSTANCE"

ALLOC=$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query "Addresses[0].AllocationId" --output text)
if [ "$ALLOC" = "None" ]; then
  ALLOC=$(aws ec2 allocate-address --domain vpc \
          --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" \
          --query AllocationId --output text)
fi
aws ec2 associate-address --instance-id "$INSTANCE" --allocation-id "$ALLOC" >/dev/null
IP=$(aws ec2 describe-addresses --allocation-ids "$ALLOC" --query "Addresses[0].PublicIp" --output text)

echo
echo "Server:  $INSTANCE at $IP"
echo "Site:    https://${IP//./-}.sslip.io"
echo "Next:    bash deploy/push.sh $IP"
