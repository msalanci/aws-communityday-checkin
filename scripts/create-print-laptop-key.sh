#!/usr/bin/env bash
# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Creates the print laptop's AWS access key and shows it once, with what to type on the laptop.
#
# Usage: scripts/create-print-laptop-key.sh
#
# The key belongs to the IAM user that may only receive and delete print requests. It is created here,
# not by Terraform, so its secret never reaches the Terraform state; it is not stored anywhere by this
# script. Refuses when the user already has a key (delete it first with delete-print-laptop-keys.sh).

set -euo pipefail
source "$(dirname "$0")/common.sh"

# Creates the key and prints the two files to create on the print laptop.
# Arguments:
#   None.
# Returns:
#   0 after printing the key once.
main() {
  local user region count created key_id secret
  load_outputs
  user="$(tf_output print_laptop_user_name)"
  region="$(tf_output aws_region)"
  count="$(aws iam list-access-keys --user-name "$user" --query 'length(AccessKeyMetadata)' --output text)"
  [[ "$count" == "0" ]] || fail "$user already has $count access key(s); delete them with scripts/delete-print-laptop-keys.sh first"
  created="$(aws iam create-access-key --user-name "$user" \
    --query 'AccessKey.[AccessKeyId,SecretAccessKey]' --output text)"
  read -r key_id secret <<< "$created"
  cat <<EOF
Access key created for $user. It is shown only now: put it on the print laptop straight away.

On the print laptop, create the folder C:\\Users\\<you>\\.aws and in it two files without extension:

  credentials
    [cd-print-laptop]
    aws_access_key_id = $key_id
    aws_secret_access_key = $secret

  config
    [profile cd-print-laptop]
    region = $region

(With the AWS CLI installed on the laptop, "aws configure --profile cd-print-laptop" writes both.)
EOF
}

main "$@"
