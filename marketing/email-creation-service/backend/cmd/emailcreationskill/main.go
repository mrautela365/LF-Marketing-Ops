// Command emailcreationskill runs the email-creation service HTTP server.
package main

import (
	"log"
	"os"

	"github.com/linuxfoundation/lfx-v2-emailcreation-service/internal/infrastructure/config"
)

func main() {
	root, err := os.Getwd()
	if err != nil {
		log.Fatalf("getwd: %v", err)
	}

	cfg, err := config.Load(root)
	if err != nil {
		log.Fatalf("load config: %v", err)
	}

	srv := NewServer(cfg)
	addr := envOr("PORT", "8000")
	log.Printf("listening on :%s", addr)
	if err := srv.ListenAndServe(":" + addr); err != nil {
		log.Fatalf("server: %v", err)
	}
}

func envOr(key, fallback string) string {
	if v, ok := os.LookupEnv(key); ok && v != "" {
		return v
	}
	return fallback
}
