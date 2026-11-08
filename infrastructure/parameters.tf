# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The two non-secret SSM parameters the scan_reprint Lambda reads: the pretix organizer slug and the check-in list ID.
# Terraform creates them with a placeholder and never touches their values again, which a script sets.
# The pretix token and the staff PIN are not here: scripts create them, so no secret reaches the state.

resource "aws_ssm_parameter" "pretix_organizer" {
  name        = "${var.ssm_prefix}/pretix/organizer"
  description = "pretix organizer slug, set by script"
  type        = "String"
  value       = "set-by-script"

  lifecycle {
    ignore_changes = [value, insecure_value]
  }
}

resource "aws_ssm_parameter" "pretix_checkin_list_id" {
  name        = "${var.ssm_prefix}/pretix/checkin-list-id"
  description = "pretix check-in list ID, set by script"
  type        = "String"
  value       = "set-by-script"

  lifecycle {
    ignore_changes = [value, insecure_value]
  }
}
