variable "oauth_user_email" {
  description = "Optional Google Desktop OAuth user principal. Null creates no IAM bindings. Do not put login secrets or tokens here."
  type        = string
  default     = null
  nullable    = true

  validation {
    condition = (
      var.oauth_user_email == null ||
      can(regex("^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$", var.oauth_user_email))
    )
    error_message = "oauth_user_email must be a plain email address, not a service account, JSON key or IAM member string."
  }
}
