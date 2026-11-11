# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# The two non-secret SSM parameters the scan-print Lambda reads: the pretix organizer slug and the check-in list ID,
# with their values from the pretix_organizer and pretix_checkin_list_id variables.
# The pretix token and the staff PIN are not here: scripts create them, so no secret reaches the state.

resource "aws_ssm_parameter" "pretix_organizer" {
  name        = "${var.ssm_prefix}/pretix/organizer"
  description = "pretix organizer slug"
  type        = "String"
  value       = var.pretix_organizer
}

resource "aws_ssm_parameter" "pretix_checkin_list_id" {
  name        = "${var.ssm_prefix}/pretix/checkin-list-id"
  description = "pretix check-in list ID"
  type        = "String"
  value       = var.pretix_checkin_list_id
}
