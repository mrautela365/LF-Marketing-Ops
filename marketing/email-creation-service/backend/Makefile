.PHONY: apigen build test vet run

GOBIN := $(CURDIR)/../../emailcreationskill/.gobin

apigen:
	PATH="$(GOBIN):$$PATH" goa gen github.com/linuxfoundation/lfx-v2-emailcreation-service/design -o .

build:
	go build ./...

vet:
	go vet ./...

test:
	go test ./...

run:
	go run ./cmd/emailcreationskill
