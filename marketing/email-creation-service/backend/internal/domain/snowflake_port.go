package domain

// SnowflakeClient runs read-only SQL queries against Snowflake, porting
// audience_tools.py's snowflake_query.
type SnowflakeClient interface {
	// Query runs sql and returns column names, row maps (column -> JSON-safe
	// value), and the row count — ports snowflake_query.
	Query(sql string) (columns []string, rows []map[string]any, err error)
}
