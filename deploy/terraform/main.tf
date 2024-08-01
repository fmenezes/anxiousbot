provider "aws" {}

terraform {
  backend "s3" {
    bucket         = "anxiousbot-main-bucket"
    key            = "terraform/terraform.tfstate"
    encrypt        = true
    dynamodb_table = "terraform-locks-table"
    region         = "us-east-1"
  }
}

# S3 Bucket
data "aws_s3_bucket" "main" {
  bucket = "anxiousbot-main-bucket"
}

# VPC
resource "aws_vpc" "main" {
  cidr_block = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name    = "anxiousbot-main-vpc"
    Project = "anxiousbot"
  }
}

# Subnet
resource "aws_subnet" "main" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = "us-east-1a"

  tags = {
    Name    = "anxiousbot-main-subnet"
    Project = "anxiousbot"
  }
}

# Internet Gateway
resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name    = "anxiousbot-main-igw"
    Project = "anxiousbot"
  }
}

# Route Table
resource "aws_route_table" "main" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name    = "anxiousbot-main-route-table"
    Project = "anxiousbot"
  }
}

# Route Table Association
resource "aws_route_table_association" "main" {
  subnet_id      = aws_subnet.main.id
  route_table_id = aws_route_table.main.id
}

# Security Group
resource "aws_security_group" "allow_ssh" {
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name    = "anxiousbot-allow-ssh"
    Project = "anxiousbot"
  }
}

# IAM Role for EC2
resource "aws_iam_role" "ec2_role" {
  name = "anxiousbot-ec2-role"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Action": "sts:AssumeRole",
      "Effect": "Allow",
      "Principal": {
        "Service": "ec2.amazonaws.com"
      }
    }
  ]
}
EOF
}

# IAM Policy for CloudWatch
resource "aws_iam_policy" "cloudwatch_policy" {
  name = "anxiousbot-cloudwatch-policy"

  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents",
        "logs:DescribeLogStreams",
        "logs:DescribeLogGroups",
        "cloudwatch:PutMetricData"
      ],
      "Resource": "*"
    }
  ]
}
EOF
}

# Attach Policy to Role
resource "aws_iam_role_policy_attachment" "attach_cloudwatch_policy" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.cloudwatch_policy.arn
}

# IAM Instance Profile
resource "aws_iam_instance_profile" "ec2_instance_profile" {
  name = "anxiousbot-instance-profile"
  role = aws_iam_role.ec2_role.name
}

# S3 Bucket Access Policy
resource "aws_iam_policy" "s3_bucket_access" {
  name        = "s3BucketAccessPolicy"
  description = "Policy for allowing EC2 instance to upload to S3 bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "s3:ListBucket",
        ]
        Effect   = "Allow"
        Resource = "${data.aws_s3_bucket.main.arn}"
      },
      {
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:PutObjectAcl",
        ]
        Effect   = "Allow"
        Resource = "${data.aws_s3_bucket.main.arn}/*"
      },
    ]
  })
}

# Attach S3 Access Policy to IAM Role
resource "aws_iam_role_policy_attachment" "attach_s3_access_policy" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.s3_bucket_access.arn
}

resource "aws_security_group" "cache_sg" {
  vpc_id = aws_vpc.main.id

  ingress {
    from_port   = 11211
    to_port     = 11211
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]  # or the specific IP range of your EC2 instances
  }

  tags = {
    Name    = "anxiousbot-cache-sg"
    Project = "anxiousbot"
  }
}

# Cache subnet
resource "aws_elasticache_subnet_group" "cache_subnet_group" {
  name       = "anxiousbot-cache-subnet-group"
  subnet_ids = [aws_subnet.main.id]

  tags = {
    Name    = "anxiousbot-cache-subnet-group"
    Project = "anxiousbot"
  }
}

# Cache cluster
resource "aws_elasticache_cluster" "cache_cluster" {
  cluster_id           = "anxiousbot-cache-cluster"
  engine               = "redis"
  node_type            = "cache.t2.small"
  num_cache_nodes      = 1
  security_group_ids   = [aws_security_group.cache_sg.id]
  subnet_group_name    = aws_elasticache_subnet_group.cache_subnet_group.name

  tags = {
    Name    = "anxiousbot-cache-cluster"
    Project = "anxiousbot"
  }
}

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "anxiousbot-errors"

  dashboard_body = jsonencode(
    {
      "widgets": [
        {
          "type": "log",
          "x": 0,
          "y": 0,
          "width": 24,
          "height": 15,
          "properties": {
            "query": "SOURCE 'anxiousbot-logs' | fields @timestamp, msg, taskName, config, exc_formatted\n| sort @timestamp desc\n| filter levelname = \"ERROR\"",
            "region": "us-east-1",
            "title": "Errors",
            "view": "table"
          }
        }
      ]
    }
  )
}

data "external" "count_config_files" {
  program = ["bash", "count_config_files.sh"]
}

resource "aws_key_pair" "anxiousbot_key" {
  key_name   = "anxiousbot-key"
  public_key = file("~/.ssh/anxiousbot_key.pub")
}

# EC2 Instance
resource "aws_instance" "server" {
  count                       = data.external.count_config_files.result.files
  ami                         = "ami-01b799c439fd5516a"
  instance_type               = "t2.medium"
  subnet_id                   = aws_subnet.main.id
  vpc_security_group_ids      = [aws_security_group.allow_ssh.id]
  associate_public_ip_address = true
  key_name                    = aws_key_pair.anxiousbot_key.key_name
  iam_instance_profile        = aws_iam_instance_profile.ec2_instance_profile.name

  user_data = <<-EOF
    #!/bin/bash
    mkdir -p /etc/anxiousbot
    echo 'S3BUCKET="${data.aws_s3_bucket.main.bucket}"' >> /etc/anxiousbot/.env
    echo 'CONFIG_PATH="config/config-${count.index}.json"' >> /etc/anxiousbot/.env
    echo 'CACHE_ENDPOINT="${aws_elasticache_cluster.cache_cluster.configuration_endpoint}"' >> /etc/anxiousbot/.env
  EOF

  tags = {
    Name    = "anxiousbot-${count.index}"
    Project = "anxiousbot"
  }
}

output "instance_ids" {
  description = "List of instance IDs"
  value       = [for instance in aws_instance.server : instance.id]
}

output "public_ips" {
  description = "List of public IP addresses"
  value       = [for instance in aws_instance.server : instance.public_ip]
}
