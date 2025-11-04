up:
	docker build -t pdf-to-json-api .
	docker run -dp 3002:3002 --name pdf_to_json pdf-to-json-api

down:
	docker stop pdf_to_json || true
	docker rm pdf_to_json || true
