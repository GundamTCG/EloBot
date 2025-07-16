# Use the latest stable Python image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Copy requirements and source code
COPY requirements.txt .
COPY . .

# Install dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# Run the bot
CMD ["python", "main.py"]
