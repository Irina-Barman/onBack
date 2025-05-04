.PHONY: run
run:
	docker-compose up --build

.PHONY: freeze
freeze:
	pip freeze >> ./onfine/requirements.txt
