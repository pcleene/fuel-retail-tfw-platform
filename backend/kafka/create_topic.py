"""Create the FuelRetail-fraud-events Kafka topic on MSK."""
import asyncio
import ssl
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.abc import AbstractTokenProvider
from aws_msk_iam_sasl_signer import MSKAuthTokenProvider

AWS_REGION = "ap-southeast-1"
BROKERS = "<msk-broker>:9098,<msk-broker>:9098"
TOPIC = "FuelRetail-fraud-events"


class MSKTokenProvider(AbstractTokenProvider):
    async def token(self):
        auth_token, _ = MSKAuthTokenProvider.generate_auth_token(AWS_REGION)
        return auth_token


async def main():
    ssl_context = ssl.create_default_context()
    admin = AIOKafkaAdminClient(
        bootstrap_servers=BROKERS,
        security_protocol="SASL_SSL",
        sasl_mechanism="OAUTHBEARER",
        sasl_oauth_token_provider=MSKTokenProvider(),
        ssl_context=ssl_context,
    )
    await admin.start()

    # List existing topics
    topics = await admin.list_topics()
    print(f"Existing topics: {topics}")

    if TOPIC in topics:
        print(f"Topic '{TOPIC}' already exists!")
    else:
        new_topic = NewTopic(name=TOPIC, num_partitions=3, replication_factor=2)
        try:
            await admin.create_topics([new_topic])
            print(f"Created topic '{TOPIC}' (3 partitions, replication=2)")
        except Exception as e:
            print(f"Error creating topic: {e}")

    # Verify
    topics = await admin.list_topics()
    print(f"Topics after: {topics}")
    await admin.close()


if __name__ == "__main__":
    asyncio.run(main())
