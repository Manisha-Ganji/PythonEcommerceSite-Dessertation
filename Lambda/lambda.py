import boto3
import json
import os

# AWS Resource Configurations
PRIMARY_S3_BUCKET = "your-primary-bucket"
SECONDARY_S3_BUCKET = "your-secondary-bucket"
S3_HEALTH_CHECK_OBJECT = "health-check.txt"

PRIMARY_RDS_CLUSTER = "your-primary-rds-cluster"
SECONDARY_RDS_CLUSTER = "your-secondary-rds-cluster"

PRIMARY_ROUTE53_RECORD = "primary-app.yourdomain.com"
SECONDARY_ROUTE53_RECORD = "secondary-app.yourdomain.com"
HOSTED_ZONE_ID = "ZXXXXXXXXXX"  # Replace with your hosted zone ID

# AWS Clients
s3_client = boto3.client('s3')
ssm_client = boto3.client('ssm')
rds_client = boto3.client('rds')
route53_client = boto3.client('route53')

def lambda_handler(event, context):
    """
    Handles disaster recovery based on CloudWatch alarm triggers.
    """
    print("Received event:", json.dumps(event))

    alarm_name = event['detail']['alarmName']
    
    if "S3" in alarm_name:
        handle_s3_failover()
    elif "RDS" in alarm_name:
        handle_rds_failover()
    elif any(x in alarm_name for x in ["EC2", "ALB", "ASG"]):
        handle_ec2_alb_asg_failover()
    else:
        print("Unknown failure detected. No action taken.")
    
    return {
        'statusCode': 200,
        'body': json.dumps('Disaster recovery execution completed!')
    }

### S3 Failover ###
def handle_s3_failover():
    """Switches to the secondary S3 bucket if the primary fails."""
    if not check_s3_health(PRIMARY_S3_BUCKET):
        print("Primary S3 bucket is down. Switching to secondary bucket.")
        update_ssm_parameter("/ecommerce/s3_bucket", SECONDARY_S3_BUCKET)
    else:
        print("Primary S3 bucket is healthy. No action needed.")

def check_s3_health(bucket_name):
    """Checks if the S3 bucket is accessible."""
    try:
        s3_client.head_object(Bucket=bucket_name, Key=S3_HEALTH_CHECK_OBJECT)
        return True
    except Exception as e:
        print(f"S3 bucket check failed: {e}")
        return False

### RDS Failover ###
def handle_rds_failover():
    """Triggers failover to the standby RDS instance."""
    try:
        response = rds_client.failover_db_cluster(DBClusterIdentifier=PRIMARY_RDS_CLUSTER)
        print("RDS failover initiated:", response)
    except Exception as e:
        print(f"Failed to initiate RDS failover: {e}")

### EC2/ALB/ASG Failover ###
def handle_ec2_alb_asg_failover():
    """Updates Route 53 to direct traffic to the secondary AWS region."""
    try:
        response = route53_client.change_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            ChangeBatch={
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': PRIMARY_ROUTE53_RECORD,
                        'Type': 'A',
                        'AliasTarget': {
                            'HostedZoneId': HOSTED_ZONE_ID,
                            'DNSName': SECONDARY_ROUTE53_RECORD,
                            'EvaluateTargetHealth': True
                        }
                    }
                }]
            }
        )
        print("Updated Route 53 to failover traffic:", response)
    except Exception as e:
        print(f"Failed to update Route 53: {e}")

### SSM Update ###
def update_ssm_parameter(name, value):
    """Updates AWS Systems Manager Parameter Store."""
    try:
        response = ssm_client.put_parameter(Name=name, Value=value, Type="String", Overwrite=True)
        print(f"Updated SSM Parameter: {name} -> {value}")
        return response
    except Exception as e:
        print(f"Error updating SSM parameter: {e}")
