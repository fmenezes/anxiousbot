provider "aws" {
  region = "eu-west-1"
}

resource "aws_s3_bucket" "main" {
  bucket = "anxiousbot-bucket"
  tags = {
    Name    = "anxiousbot-bucket"
    Project = "anxiousbot"
  }
}

resource "aws_dynamodb_table" "terraform_locks" {
  name         = "terraform-locks-table"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = {
    Name = "anxiousbot-terraform-lock-table"
    Project = "anxiousbot"
  }
}

resource "aws_eip" "primary_server_ip" {
  tags = {
    Name = "anxiousbot-primary-server-ip"
    Project = "anxiousbot"
  }
}
