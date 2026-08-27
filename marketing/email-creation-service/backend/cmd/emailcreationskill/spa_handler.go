package main

import (
	"net/http"
	"os"
	"path/filepath"
	"strings"
)

// mountSPARoutes serves the built Angular frontend's static assets and a
// classic SPA catch-all fallback, porting main.py's FRONTEND_DIR static
// mount + "/" + "/{full_path:path}" routes. Must be mounted last so its
// wildcard route never shadows the API routes registered earlier.
//
// If frontendDir doesn't exist (this Go service's frontend has no built
// dist/ checked in yet — see config.Config.FrontendDir's doc comment), this
// no-ops: chi's default 404 handler takes over instead of failing startup.
func (s *Server) mountSPARoutes(frontendDir string) {
	if frontendDir == "" {
		return
	}
	if info, err := os.Stat(frontendDir); err != nil || !info.IsDir() {
		return
	}

	indexPath := filepath.Join(frontendDir, "index.html")
	fileServer := http.FileServer(http.Dir(frontendDir))

	s.router.Get("/*", func(w http.ResponseWriter, r *http.Request) {
		reqPath := strings.TrimPrefix(r.URL.Path, "/")
		if reqPath == "" {
			http.ServeFile(w, r, indexPath)
			return
		}
		full := filepath.Join(frontendDir, filepath.FromSlash(reqPath))
		if info, err := os.Stat(full); err == nil && !info.IsDir() {
			fileServer.ServeHTTP(w, r)
			return
		}
		// SPA fallback: unknown paths (client-side routes) serve index.html.
		http.ServeFile(w, r, indexPath)
	})
}
