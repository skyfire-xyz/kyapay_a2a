# Dappier dataset configuration
DATASET_BASE_URL = "https://pub-303d212fa4df4073b8b38b3de4a72d89.r2.dev/Dappier"

# Mock Dappier dataset catalog
DAPPIER_DATASETS = [
    {
        "id": 1,
        "dataId": 1,
        "title": "US Automobile Data - 2024",
        "size": "20MB",
        "description": "Data specifically for the year of 2024.",
        "price": "0.002",
        "sampleDataFormat": {
            "type": "csv",
            "headers": "Manufacturer,Model,Month,Unit Sales"
        },
        "dataUrl": f"{DATASET_BASE_URL}/demo-dataset1.csv"
    },
    {
        "id": 2,
        "dataId": 2,
        "title": "US Automobile Data - 2025",
        "size": "10MB",
        "description": "Data specifically for the year of 2025.",
        "price": "0.003",
        "sampleDataFormat": {
            "type": "csv",
            "headers": "Manufacturer,Model,Month,Unit Sales"
        },
        "dataUrl": f"{DATASET_BASE_URL}/demo-dataset2.csv"
    }
]