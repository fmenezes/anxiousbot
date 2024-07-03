provider "aws" {
  region = "us-east-1"
}

# S3 Bucket
resource "aws_s3_bucket" "main" {
  bucket = "anxiousbot-main-bucket"
  tags = {
    Name    = "anxiousbot-main-bucket"
    Project = "anxiousbot"
  }
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
          "s3:PutObject",
          "s3:PutObjectAcl",
        ]
        Effect   = "Allow"
        Resource = "${aws_s3_bucket.main.arn}/*"
      },
    ]
  })
}

# Attach S3 Access Policy to IAM Role
resource "aws_iam_role_policy_attachment" "attach_s3_access_policy" {
  role       = aws_iam_role.ec2_role.name
  policy_arn = aws_iam_policy.s3_bucket_access.arn
}

# EC2 Instance
resource "aws_instance" "server" {
  ami                         = "ami-01b799c439fd5516a"
  instance_type               = "t2.small"
  subnet_id                   = aws_subnet.main.id
  vpc_security_group_ids      = [aws_security_group.allow_ssh.id]
  associate_public_ip_address = true
  key_name                    = "filipe"
  iam_instance_profile        = aws_iam_instance_profile.ec2_instance_profile.name

  user_data = <<-EOF
    #!/bin/bash
    echo 'export S3BUCKET="${aws_s3_bucket.main.bucket}"' >> /etc/profile.d/anxiousbot.sh
    echo 'export SYMBOLS="BTC/USDT"' >> /etc/profile.d/anxiousbot.sh
    echo 'export EXCHANGES="whitebit,exmo,mexc,bingx,bitmex,htx,bitcoincom,woo,coinbase,lbank,hollaex,gate,currencycom,upbit,bitstamp,bitrue,deribit,phemex,cex,bitfinex,kraken,probit,ascendex,bybit,bitget,kucoin,luno,gemini,blockchaincom,coinex,hitbtc,huobi,binance,bitopro,bitmart,bitfinex2,ndax,poloniex,wazirx,coinbaseexchange,gateio,binanceus,bequant,p2b,cryptocom,okx"' >> /etc/profile.d/anxiousbot.sh
    source /etc/profile.d/anxiousbot.sh
  EOF

  tags = {
    Name    = "anxiousbot-server-BTC/USDT"
    Project = "anxiousbot"
  }
}

output "instance_id" {
  description = "The ID of the EC2 instance"
  value       = aws_instance.server.id
}

output "public_ip" {
  description = "The public IP of the EC2 instance"
  value       = aws_instance.server.public_ip
}
