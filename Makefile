CLUSTER ?= platform
NS      ?= platform
LLM_API_KEY ?=
SVCS = gateway dashboard woo-mcp demo-mcp

.PHONY: up cluster images import deploy creds lint down smoke

up: cluster images import deploy creds

cluster:
	k3d cluster list | grep -q '^$(CLUSTER) ' || k3d cluster create $(CLUSTER) -p "8080:80@loadbalancer" --wait

images:
	@for s in $(SVCS); do docker build -t platform/$$s:dev services/$$s || exit 1; done

import:
	k3d image import $(foreach s,$(SVCS),platform/$(s):dev) -c $(CLUSTER)

deploy:
	helm upgrade --install platform charts/platform -n $(NS) --create-namespace \
	  -f charts/platform/values-local.yaml $(if $(LLM_API_KEY),--set secrets.llmApiKey=$(LLM_API_KEY),) \
	  --wait --timeout 20m
	kubectl -n $(NS) rollout restart deploy/gateway >/dev/null

creds:
	@echo "Dashboard: http://admin.localtest.me:8080  user: admin@example.com"
	@echo -n "Dashboard admin password: "; kubectl -n $(NS) get secret platform-secrets -o jsonpath='{.data.dashboard-admin-password}' | base64 -d; echo
	@echo "Storefront: http://shop.localtest.me:8080  (WP admin /wp-admin, user admin)"
	@echo -n "WordPress admin password: "; kubectl -n $(NS) get secret platform-secrets -o jsonpath='{.data.wp-admin-password}' | base64 -d; echo

lint:
	helm lint charts/platform -f charts/platform/values-local.yaml
	helm lint charts/platform -f charts/platform/values-prod.yaml

down:
	k3d cluster delete $(CLUSTER)
