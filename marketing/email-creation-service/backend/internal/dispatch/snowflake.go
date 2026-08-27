package dispatch

import (
	"crypto/rsa"
	"crypto/x509"
	"database/sql"
	"encoding/pem"
	"fmt"
	"strings"
	"time"

	sf "github.com/snowflakedb/gosnowflake"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/domain"
)

// SnowflakeClient ports audience_tools.py's _sf_private_key_bytes,
// _sf_connect, _sf_json_safe, and snowflake_query.
type SnowflakeClient struct {
	Account    string
	User       string
	PrivateKey string // PEM, as read from SNOWFLAKE_PRIVATE_KEY
	Database   string
	Schema     string
	Warehouse  string
	Role       string
}

var _ domain.SnowflakeClient = (*SnowflakeClient)(nil)

// NewSnowflakeClient builds a Snowflake adapter from config fields.
func NewSnowflakeClient(account, user, privateKeyPEM, database, schema, warehouse, role string) *SnowflakeClient {
	return &SnowflakeClient{
		Account:    account,
		User:       user,
		PrivateKey: privateKeyPEM,
		Database:   database,
		Schema:     schema,
		Warehouse:  warehouse,
		Role:       role,
	}
}

// privateKey ports _sf_private_key_bytes — cleans up common .env copy/paste
// mistakes (stray wrapping quotes, literal \n / \r\n escapes, real CRLF line
// endings) before parsing the unencrypted PKCS8 PEM key.
func (c *SnowflakeClient) privateKey() (*rsa.PrivateKey, error) {
	pemStr := strings.TrimSpace(c.PrivateKey)
	if pemStr == "" {
		return nil, fmt.Errorf("SNOWFLAKE_PRIVATE_KEY not set")
	}
	if len(pemStr) >= 2 && pemStr[0] == pemStr[len(pemStr)-1] && (pemStr[0] == '\'' || pemStr[0] == '"') {
		pemStr = strings.TrimSpace(pemStr[1 : len(pemStr)-1])
	}
	pemStr = strings.ReplaceAll(pemStr, "\\r\\n", "\n")
	pemStr = strings.ReplaceAll(pemStr, "\\n", "\n")
	pemStr = strings.ReplaceAll(pemStr, "\r\n", "\n")
	pemStr = strings.ReplaceAll(pemStr, "\r", "\n")

	block, _ := pem.Decode([]byte(pemStr))
	if block == nil {
		return nil, fmt.Errorf(
			"Failed to parse SNOWFLAKE_PRIVATE_KEY as a PEM key. " +
				"Check that .env holds the full unencrypted PKCS8 PEM " +
				"(BEGIN/END PRIVATE KEY lines) with line breaks preserved as literal \\n.",
		)
	}
	key, err := x509.ParsePKCS8PrivateKey(block.Bytes)
	if err != nil {
		return nil, fmt.Errorf(
			"Failed to parse SNOWFLAKE_PRIVATE_KEY as a PEM key (%w). "+
				"Check that .env holds the full unencrypted PKCS8 PEM "+
				"(BEGIN/END PRIVATE KEY lines) with line breaks preserved as literal \\n.",
			err,
		)
	}
	rsaKey, ok := key.(*rsa.PrivateKey)
	if !ok {
		return nil, fmt.Errorf("SNOWFLAKE_PRIVATE_KEY is not an RSA private key")
	}
	return rsaKey, nil
}

// connect ports _sf_connect.
func (c *SnowflakeClient) connect() (*sql.DB, error) {
	missing := []string{}
	if c.Account == "" {
		missing = append(missing, "SNOWFLAKE_ACCOUNT")
	}
	if c.User == "" {
		missing = append(missing, "SNOWFLAKE_USER")
	}
	if strings.TrimSpace(c.PrivateKey) == "" {
		missing = append(missing, "SNOWFLAKE_PRIVATE_KEY")
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("Snowflake env vars not set: %s", strings.Join(missing, ", "))
	}

	rsaKey, err := c.privateKey()
	if err != nil {
		return nil, err
	}

	database := c.Database
	if database == "" {
		database = "ANALYTICS"
	}
	schema := c.Schema
	if schema == "" {
		schema = "Silver_Segment"
	}

	cfg := &sf.Config{
		Account:       c.Account,
		User:          c.User,
		Authenticator: sf.AuthTypeJwt,
		PrivateKey:    rsaKey,
		Database:      database,
		Schema:        schema,
		Warehouse:     c.Warehouse,
		Role:          c.Role,
	}
	dsn, err := sf.DSN(cfg)
	if err != nil {
		return nil, err
	}
	return sql.Open("snowflake", dsn)
}

// sfJSONSafe ports _sf_json_safe — converts a Snowflake column value
// (date/datetime/Decimal/etc.) to a JSON-serializable type.
func sfJSONSafe(v any) any {
	switch val := v.(type) {
	case time.Time:
		return val.Format(time.RFC3339Nano)
	default:
		return val
	}
}

// Query ports snowflake_query.
func (c *SnowflakeClient) Query(query string) ([]string, []map[string]any, error) {
	db, err := c.connect()
	if err != nil {
		return nil, nil, err
	}
	defer db.Close()

	rows, err := db.Query(query)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()

	cols, err := rows.Columns()
	if err != nil {
		return nil, nil, err
	}

	out := make([]map[string]any, 0)
	for rows.Next() {
		values := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range values {
			ptrs[i] = &values[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, nil, err
		}
		row := make(map[string]any, len(cols))
		for i, col := range cols {
			row[col] = sfJSONSafe(values[i])
		}
		out = append(out, row)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}

	return cols, out, nil
}
