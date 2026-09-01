# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

variable "project_id" {
  description = "GCP project ID"
  type        = string
}

variable "region" {
  description = "GCP region — pick one with L4 quota"
  type        = string
  default     = "us-central1"
}

variable "zone" {
  description = "GCP zone — must have the GPU type available (L4: us-central1-a/b/c, NOT -f)"
  type        = string
  default     = "us-central1-a"
}

variable "cluster_name" {
  description = "GKE cluster name"
  type        = string
  default     = "jax-gpu-cluster"
}

variable "machine_type" {
  description = "Machine type for GPU nodes (g2-standard-24 = 2× L4, g2-standard-48 = 4× L4)"
  type        = string
  default     = "g2-standard-24"
}

variable "gpu_type" {
  description = "GPU accelerator type"
  type        = string
  default     = "nvidia-l4"
}

variable "gpu_count" {
  description = "Number of GPUs per node — must match the machine_type"
  type        = number
  default     = 2
}
