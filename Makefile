.PHONY: deploy
deploy:
	cd deploy/terraform; \
	terraform import aws_s3_bucket.main anxiousbot-main-bucket; \
	terraform apply -auto-approve; \
	cd ../ansible; \
	ansible-playbook playbook-setup.yml; \
	cd ../..

.PHONY: destroy
destroy:
	cd deploy/terraform; \
	terraform state rm aws_s3_bucket.main; \
	terraform apply -destroy -auto-approve; \
	cd ../..
