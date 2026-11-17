# Use a base image with Go installed
FROM golang:latest AS builder

# Set the working directory inside the container
WORKDIR /app

# Copy go module files
COPY go.mod go.sum ./

# Download Go dependencies
RUN go mod download

# Copy the source code
COPY . .

# Build the Go application
RUN go build -o main .

# Use a minimal base image for the final container
FROM alpine:latest  

# Set the working directory
WORKDIR /root/

# Copy the binary from the builder stage
COPY --from=builder /app/main .

# Expose the port the app listens on
EXPOSE 8080

# Command to run when the container starts
CMD ["./main"]
