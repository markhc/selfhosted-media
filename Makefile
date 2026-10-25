.DEFAULT_GOAL := help

PYTHON ?= python3
VENV := .venv
ANSIBLE_PLAYBOOK := $(VENV)/bin/ansible-playbook
ANSIBLE_VAULT := $(VENV)/bin/ansible-vault
ANSIBLE_GALAXY := $(VENV)/bin/ansible-galaxy
ANSIBLE_LINT := $(VENV)/bin/ansible-lint
INVENTORY_DIR := ansible/inventories/local
VAULT_FILE := $(INVENTORY_DIR)/vault.yml
VAULT_TEMPLATE := ansible/inventories/example/vault.example.yml
VAULT_PASSWORD_FILE ?= .vault-password
COLLECTION_STAMP := .ansible/collections/.installed

VAULT_ARGS = $(if $(wildcard $(VAULT_PASSWORD_FILE)),--vault-password-file $(VAULT_PASSWORD_FILE),--ask-vault-pass)
BECOME_ARGS = $(if $(filter 1 true yes,$(ASK_BECOME_PASS)),--ask-become-pass,)
POLICY_FILE_ARG = $(if $(POLICY_FILE),--extra-vars tailnet_policy_file=$(POLICY_FILE),)

.PHONY: help configure setup inventory vault-init vault-edit deploy \
	tailscale-status policy-preview policy-apply policy-replace require-apply-mode check syntax lint test clean

help:
	@echo "Common targets:"
	@echo "  make configure         Install tools, create local inventory, and initialize the vault"
	@echo "  make deploy            Deploy every service enabled in the local inventory"
	@echo "  make deploy-<service>  Deploy only Docker and one selected service (e.g. deploy-caddy)"
	@echo "  make tailscale-status  Show selected hosts' enrollment state and active tailnet"
	@echo "  make vault-edit        Edit encrypted deployment credentials"
	@echo "  make policy-preview    Validate and preview the tailnet policy"
	@echo "  make policy-apply      Apply only to an untouched default tailnet policy"
	@echo "  make policy-replace    Explicitly replace an existing tailnet policy"
	@echo "  make check             Run syntax, lint, and unit checks"
	@echo
	@echo "Options: ASK_BECOME_PASS=1, POLICY_FILE=/absolute/path, ANSIBLE_ARGS='...'"

configure:
	@$(MAKE) --no-print-directory setup
	@$(MAKE) --no-print-directory vault-init

setup: $(ANSIBLE_PLAYBOOK) $(COLLECTION_STAMP) inventory

$(ANSIBLE_PLAYBOOK): requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(VENV)/bin/python -m pip install -r requirements-dev.txt

$(COLLECTION_STAMP): ansible/requirements.yml $(ANSIBLE_PLAYBOOK)
	mkdir -p .ansible/collections
	$(ANSIBLE_GALAXY) collection install --collections-path .ansible/collections -r ansible/requirements.yml
	touch $(COLLECTION_STAMP)

inventory:
	@if [ ! -d "$(INVENTORY_DIR)" ]; then \
		cp -R ansible/inventories/example "$(INVENTORY_DIR)"; \
		echo "Created $(INVENTORY_DIR); update hosts.yml and group_vars/all.yml."; \
	fi

vault-init: $(ANSIBLE_PLAYBOOK) inventory
	@if [ -f "$(VAULT_FILE)" ]; then \
		echo "$(VAULT_FILE) already exists; use 'make vault-edit' to change it."; \
	else \
		cp "$(VAULT_TEMPLATE)" "$(VAULT_FILE)"; \
		$(ANSIBLE_VAULT) encrypt $(VAULT_ARGS) "$(VAULT_FILE)" && \
		$(ANSIBLE_VAULT) edit $(VAULT_ARGS) "$(VAULT_FILE)"; \
	fi

vault-edit: $(ANSIBLE_PLAYBOOK)
	@test -f "$(VAULT_FILE)" || { echo "Missing $(VAULT_FILE); run 'make vault-init'."; exit 1; }
	$(ANSIBLE_VAULT) edit $(VAULT_ARGS) "$(VAULT_FILE)"

deploy: $(ANSIBLE_PLAYBOOK) $(COLLECTION_STAMP)
	@$(MAKE) --no-print-directory require-apply-mode
	@$(MAKE) --no-print-directory require-vault
	$(ANSIBLE_PLAYBOOK) $(VAULT_ARGS) $(BECOME_ARGS) --extra-vars @$(VAULT_FILE) \
		ansible/playbooks/site.yml $(ANSIBLE_ARGS)

# Each service role is tagged with its selfhosted_services key.
deploy-%: $(ANSIBLE_PLAYBOOK) $(COLLECTION_STAMP)
	@$(MAKE) --no-print-directory require-apply-mode
	@$(MAKE) --no-print-directory require-vault
	$(ANSIBLE_PLAYBOOK) $(VAULT_ARGS) $(BECOME_ARGS) --extra-vars @$(VAULT_FILE) \
		--tags $* ansible/playbooks/site.yml $(ANSIBLE_ARGS)

tailscale-status: $(ANSIBLE_PLAYBOOK)
	$(ANSIBLE_PLAYBOOK) $(BECOME_ARGS) ansible/playbooks/tailscale-status.yml $(ANSIBLE_ARGS)

policy-preview: $(ANSIBLE_PLAYBOOK)
	@$(MAKE) --no-print-directory require-vault
	$(ANSIBLE_PLAYBOOK) $(VAULT_ARGS) -i localhost, --check --extra-vars @$(VAULT_FILE) \
		$(POLICY_FILE_ARG) ansible/playbooks/tailnet.yml $(ANSIBLE_ARGS)

policy-apply: $(ANSIBLE_PLAYBOOK)
	@$(MAKE) --no-print-directory require-vault
	$(ANSIBLE_PLAYBOOK) $(VAULT_ARGS) -i localhost, --extra-vars @$(VAULT_FILE) \
		--extra-vars tailnet_policy_apply=true $(POLICY_FILE_ARG) ansible/playbooks/tailnet.yml $(ANSIBLE_ARGS)

policy-replace: $(ANSIBLE_PLAYBOOK)
	@$(MAKE) --no-print-directory require-vault
	$(ANSIBLE_PLAYBOOK) $(VAULT_ARGS) -i localhost, --extra-vars @$(VAULT_FILE) \
		--extra-vars '{"tailnet_policy_apply":true,"tailnet_policy_replace_existing":true}' \
		$(POLICY_FILE_ARG) ansible/playbooks/tailnet.yml $(ANSIBLE_ARGS)

.PHONY: require-vault
require-vault:
	@test -f "$(VAULT_FILE)" || { echo "Missing $(VAULT_FILE); run 'make vault-init'."; exit 1; }

require-apply-mode:
	@test -z "$(filter --check -C,$(ANSIBLE_ARGS))" || { \
		echo "Deployment refused: ANSIBLE_ARGS enables check mode, which creates no containers."; \
		echo "Run 'unset ANSIBLE_ARGS' or invoke make with ANSIBLE_ARGS= for a real deployment."; \
		exit 1; \
	}

check: $(COLLECTION_STAMP) syntax lint test

syntax: $(ANSIBLE_PLAYBOOK)
	$(ANSIBLE_PLAYBOOK) -i ansible/inventories/example/hosts.yml --syntax-check ansible/playbooks/site.yml
	$(ANSIBLE_PLAYBOOK) -i localhost, --syntax-check ansible/playbooks/tailnet.yml
	$(ANSIBLE_PLAYBOOK) -i ansible/inventories/example/hosts.yml --syntax-check ansible/playbooks/tailscale-status.yml

lint: $(ANSIBLE_PLAYBOOK)
	$(ANSIBLE_LINT) ansible/playbooks/site.yml ansible/playbooks/tailnet.yml ansible/playbooks/tailscale-status.yml ansible/roles

test: $(ANSIBLE_PLAYBOOK)
	$(VENV)/bin/python -m unittest discover -s ansible/tests -v

clean:
	rm -f "$(COLLECTION_STAMP)"
