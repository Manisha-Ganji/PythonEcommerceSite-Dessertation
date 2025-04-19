import boto3

PRIMARY_REGION = 'us-east-1'
SECONDARY_REGION = 'us-west-1'

PRIMARY_ALB_DNS = 'your-primary-alb.us-east-1.elb.amazonaws.com'
SECONDARY_ALB_DNS = 'your-secondary-alb.us-west-1.elb.amazonaws.com'
HOSTED_ZONE_ID = 'ZXXXXXXXXXXXXX'  # Replace with your actual hosted zone ID
RECORD_NAME = 'yourdomain.com.'    # Your DNS record, with trailing dot

def lambda_handler(event, context):
    print("🔁 Lambda triggered.")

    current_target = get_current_alb_target()
    print(f"🔍 Current ALB target: {current_target}")

    any_failure = (
        not check_rds(PRIMARY_REGION) or
        not check_s3(PRIMARY_REGION) or
        not check_ec2(PRIMARY_REGION) or
        not check_asg(PRIMARY_REGION) or
        not check_alb(PRIMARY_REGION)
    )

    if any_failure:
        print("⚠️ One or more primary services failed.")
        if current_target != SECONDARY_ALB_DNS:
            update_route53(SECONDARY_ALB_DNS)
            print("🔁 Route 53 switched to secondary ALB.")
        else:
            print("✅ Already pointing to secondary ALB. No change needed.")
    else:
        print("✅ All primary services are healthy.")
        if current_target != PRIMARY_ALB_DNS:
            update_route53(PRIMARY_ALB_DNS)
            print("🔁 Route 53 switched back to primary ALB.")
        else:
            print("✅ Already pointing to primary ALB. No change needed.")

# --- HEALTH CHECKS ---

def check_rds(region):
    try:
        rds = boto3.client('rds', region_name=region)
        for db in rds.describe_db_instances()['DBInstances']:
            if db['DBInstanceStatus'] != 'available':
                return False
        return True
    except Exception as e:
        print(f"❌ RDS health check failed: {e}")
        return False

def check_s3(region):
    try:
        s3 = boto3.client('s3', region_name=region)
        s3.head_bucket(Bucket='your-primary-s3-bucket')  # Replace with actual name
        return True
    except Exception as e:
        print(f"❌ S3 health check failed: {e}")
        return False

def check_ec2(region):
    try:
        ec2 = boto3.client('ec2', region_name=region)
        statuses = ec2.describe_instance_status(IncludeAllInstances=True)['InstanceStatuses']
        for inst in statuses:
            if inst['InstanceState']['Name'] != 'running':
                return False
        return True
    except Exception as e:
        print(f"❌ EC2 health check failed: {e}")
        return False

def check_asg(region):
    try:
        asg = boto3.client('autoscaling', region_name=region)
        for group in asg.describe_auto_scaling_groups()['AutoScalingGroups']:
            if len(group['Instances']) < group['DesiredCapacity']:
                return False
        return True
    except Exception as e:
        print(f"❌ ASG health check failed: {e}")
        return False

def check_alb(region):
    try:
        elbv2 = boto3.client('elbv2', region_name=region)
        for lb in elbv2.describe_load_balancers()['LoadBalancers']:
            if lb['State']['Code'] != 'active':
                return False
            tgs = elbv2.describe_target_groups(LoadBalancerArn=lb['LoadBalancerArn'])['TargetGroups']
            for tg in tgs:
                ths = elbv2.describe_target_health(TargetGroupArn=tg['TargetGroupArn'])['TargetHealthDescriptions']
                for th in ths:
                    if th['TargetHealth']['State'] != 'healthy':
                        return False
        return True
    except Exception as e:
        print(f"❌ ALB health check failed: {e}")
        return False

# --- ROUTE 53 LOGIC ---

def get_current_alb_target():
    try:
        route53 = boto3.client('route53')
        record = route53.list_resource_record_sets(
            HostedZoneId=HOSTED_ZONE_ID,
            StartRecordName=RECORD_NAME,
            StartRecordType='A',
            MaxItems='1'
        )['ResourceRecordSets'][0]
        return record['AliasTarget']['DNSName']
    except Exception as e:
        print(f"❌ Failed to get current ALB from Route 53: {e}")
        return None

def update_route53(alb_dns):
    region = SECONDARY_REGION if alb_dns == SECONDARY_ALB_DNS else PRIMARY_REGION
    zone_id = get_alb_zone_id(region)

    route53 = boto3.client('route53')
    route53.change_resource_record_sets(
        HostedZoneId=HOSTED_ZONE_ID,
        ChangeBatch={
            'Comment': f'Switching ALB to {alb_dns}',
            'Changes': [
                {
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': RECORD_NAME,
                        'Type': 'A',
                        'AliasTarget': {
                            'HostedZoneId': zone_id,
                            'DNSName': alb_dns,
                            'EvaluateTargetHealth': False
                        }
                    }
                }
            ]
        }
    )

def get_alb_zone_id(region):
    try:
        elbv2 = boto3.client('elbv2', region_name=region)
        lbs = elbv2.describe_load_balancers()['LoadBalancers']
        return lbs[0]['CanonicalHostedZoneId']  # Assumes 1 ALB per region
    except Exception as e:
        print(f"❌ Failed to fetch ALB Hosted Zone ID: {e}")
        raise
