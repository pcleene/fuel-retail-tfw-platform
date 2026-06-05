from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    mongodb_url: str = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"
    tls_cert_path: str = "<local-path>"
    screening_db: str = "FuelRetail_screening"
    analytics_db: str = "FuelRetail_analytics"
    fraud_db: str = "FuelRetail_fraud"
    server_host: str = "0.0.0.0"
    server_port: int = 8000

    # Kafka / MSK
    kafka_bootstrap_servers: str = "<msk-broker>:9098,<msk-broker>:9098"
    kafka_topic: str = "FuelRetail-fraud-events"

    # Voyage AI
    voyage_api_key: str = "<voyage-key>"
    voyage_model: str = "voyage-4-large"
    voyage_dimensions: int = 1024

    # Anthropic (LangGraph agent)
    anthropic_api_key: str = ""

    # UC2b: Analytics Chatbot (MCP)
    mcp_server_command: str = "/opt/homebrew/bin/mongodb-mcp-server"
    mcp_server_args: list[str] = ["--readOnly"]
    mcp_connection_string: str = "mongodb+srv://<user>:<password>@<cluster>.mongodb.net/<db>"

    # AWS Bedrock
    bedrock_region: str = "ap-southeast-1"
    bedrock_model_id: str = "apac.anthropic.claude-sonnet-4-20250514-v1:0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
