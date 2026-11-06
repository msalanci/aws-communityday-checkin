# Copyright (c) 2026-2027 Michal Salanci
# SPDX-License-Identifier: MIT

# Inputs of the app stack: region, names, the scanner page's domain, SSM, pretix and the event's time zone.

variable "aws_region" {
  type        = string
  description = "AWS region of the app stack."
  default     = "eu-central-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-[a-z]+)+-[0-9]$", var.aws_region))
    error_message = "The region must look like eu-central-1."
  }
}

variable "project_tag" {
  type        = string
  description = "Value of the project tag on every resource."
  default     = "cd-registration-app"

  validation {
    condition     = length(var.project_tag) > 0
    error_message = "The project tag must not be empty."
  }
}

variable "name_prefix" {
  type        = string
  description = "Prefix of every resource name, for example cd-registration."
  default     = "cd-registration"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,40}$", var.name_prefix))
    error_message = "The name prefix must be 1-40 lowercase letters, digits or hyphens."
  }
}

variable "domain_name" {
  type        = string
  description = "An existing public Route 53 zone in this account; the scanner page's records go into it, for example example.org."

  validation {
    condition     = can(regex("^([a-z0-9-]+\\.)+[a-z]{2,}$", var.domain_name))
    error_message = "The domain name must look like example.com, in lowercase."
  }
}

variable "subdomain" {
  type        = string
  description = "The scanner page lives at <subdomain>.<domain_name>."
  default     = "checkin"

  validation {
    condition     = can(regex("^[a-z0-9-]{1,63}$", var.subdomain))
    error_message = "The subdomain must be 1-63 lowercase letters, digits or hyphens."
  }
}

variable "ssm_prefix" {
  type        = string
  description = "Prefix of the SSM parameters: pretix organizer, check-in list ID, pretix token and staff PIN."
  default     = "/cd-registration"

  validation {
    condition     = can(regex("^/[A-Za-z0-9_./-]+[^/]$", var.ssm_prefix))
    error_message = "The SSM prefix must start with / and not end with /."
  }
}

variable "pretix_base_url" {
  type        = string
  description = "Address of pretix; change it only for a self-hosted pretix."
  default     = "https://pretix.eu"

  validation {
    condition     = can(regex("^https://[^/]+$", var.pretix_base_url))
    error_message = "The pretix address must start with https:// and have no path."
  }
}

variable "event_timezone" {
  type        = string
  description = "IANA time zone of the event, for the \"checked in at\" time."
  default     = "Europe/Bratislava"

  validation {
    condition     = length(var.event_timezone) > 0
    error_message = "The event time zone must not be empty."
  }
}

variable "event_utc_offset" {
  type        = string
  description = "Fixed UTC offset such as +01:00, used only if the Lambda runtime has no time zone data; empty for none."
  default     = ""

  validation {
    condition     = var.event_utc_offset == "" || can(regex("^[+-][0-9]{2}:[0-9]{2}$", var.event_utc_offset))
    error_message = "The UTC offset must be empty or look like +01:00."
  }
}
