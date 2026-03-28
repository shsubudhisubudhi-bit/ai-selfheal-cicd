# ============================================================
# AI Self-Healing CI/CD - Azure Infrastructure
# Deploy with: terraform init && terraform apply
# ============================================================

terraform {
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~>4.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id = var.subscription_id
}

variable "subscription_id" {
  description = "Azure Subscription ID"
  type        = string
}

variable "location" {
  default     = "East US"
  description = "Azure region"
}

variable "project_name" {
  default     = "ai-selfheal"
  description = "Project name prefix"
}

# --- Resource Group ---
resource "azurerm_resource_group" "rg" {
  name     = "${var.project_name}-rg"
  location = var.location
}

# --- Container Registry ---
resource "azurerm_container_registry" "acr" {
  name                = "${replace(var.project_name, "-", "")}acr"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  sku                 = "Basic"
  admin_enabled       = true
}

# --- App Service Plan ---
resource "azurerm_service_plan" "plan" {
  name                = "${var.project_name}-plan"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  os_type             = "Linux"
  sku_name            = "B1"
}

# --- Web App (Container) ---
resource "azurerm_linux_web_app" "app" {
  name                = "${var.project_name}-app"
  resource_group_name = azurerm_resource_group.rg.name
  location            = azurerm_resource_group.rg.location
  service_plan_id     = azurerm_service_plan.plan.id

  site_config {
    application_stack {
      docker_registry_url      = "https://${azurerm_container_registry.acr.login_server}"
      docker_registry_username = azurerm_container_registry.acr.admin_username
      docker_registry_password = azurerm_container_registry.acr.admin_password
      docker_image_name        = "selfheal-app:latest"
    }
  }

  app_settings = {
    "WEBSITES_PORT" = "9090"
    "FAIL_MODE"     = "false"
    "APP_VERSION"   = "1.0.0"
  }
}

# --- Outputs ---
output "app_url" {
  value = "https://${azurerm_linux_web_app.app.default_hostname}"
}

output "acr_login_server" {
  value = azurerm_container_registry.acr.login_server
}

output "resource_group" {
  value = azurerm_resource_group.rg.name
}
