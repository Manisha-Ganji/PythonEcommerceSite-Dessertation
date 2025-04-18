import boto3
import logging
import psycopg2
from datetime import datetime

# Initialize AWS clients
ssm = boto3.client('ssm')
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# SSM parameter names
PRIMARY_RDS_PARAM = '/eCommApp/db/primary'
SECONDARY_RDS_PARAM = '/eCommApp/db/secondary'
ACTIVE_RDS_PARAM = '/eCommApp/db/active'

def lambda_handler(event, context):
    logger.info(f"[{datetime.now()}] RDS health check triggered.")
    logger.info(f"Event received: {event}")

    try:
        # Fetch connection strings from SSM Parameter Store
        primary = ssm.get_parameter(Name=PRIMARY_RDS_PARAM)['Parameter']['Value']
        secondary = ssm.get_parameter(Name=SECONDARY_RDS_PARAM)['Parameter']['Value']
        current_active = ssm.get_parameter(Name=ACTIVE_RDS_PARAM)['Parameter']['Value']

        # If the current active DB is the primary, check its health
        if current_active == primary:
            logger.info("✅ Primary DB is active. Checking if it's healthy.")
            if is_postgres_healthy(primary):
                logger.info("✅ Primary DB is healthy. No action needed.")
            else:
                logger.warning("❌ Primary DB is unhealthy. Switching to secondary DB.")
                failover_to_secondary(secondary)
        else:
            logger.info("🔄 Currently using secondary DB. Checking if primary is healthy.")
            if is_postgres_healthy(primary):
                logger.info("✅ Primary DB is healthy. Switching back to primary DB.")
                failback_to_primary(primary)
            else:
                logger.warning("❌ Primary DB still unhealthy. Keeping secondary active.")

    except Exception as e:
        logger.error(f"❌ Lambda execution failed: {e}")
        raise


def is_postgres_healthy(conn_str):
    try:
        dbvalues = conn_str.split(',')
        conn = psycopg2.connect(
            dbname = dbvalues[0]
            user = dbvalues[1]
            password = dbvalues[2]
            host = dbvalues[3]
            port= dbvalues[4]
        )
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"⚠️ Primary DB health check failed: {e}")
        return False


def failover_to_secondary(secondary):
    """Switch to the secondary DB."""
    ssm.put_parameter(
        Name=ACTIVE_RDS_PARAM,
        Value=secondary,
        Overwrite=True
    )
    logger.info(f"✅ Failover: Switched to secondary DB {secondary}")


def failback_to_primary(primary):
    """Switch back to the primary DB."""
    ssm.put_parameter(
        Name=ACTIVE_RDS_PARAM,
        Value=primary,
        Overwrite=True
    )
    logger.info(f"✅ Failback: Switched back to primary DB {primary}")
