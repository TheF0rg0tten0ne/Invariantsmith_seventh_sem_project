def index_by_id(records):
    return {record.id: transform(record) for record in records}
