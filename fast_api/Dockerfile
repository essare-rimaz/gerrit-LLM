FROM redhat/ubi9 
WORKDIR /app/
RUN dnf install -y pip
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /app/requirements.txt
COPY main.py /app/main.py
EXPOSE 5005
CMD ["fastapi", "run", "/app/main.py", "--proxy-headers","--port", "5005"]
