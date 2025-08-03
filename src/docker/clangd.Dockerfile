FROM debian:bullseye-slim

# Install dependencies for adding repositories
RUN apt-get update && apt-get install -y \
    wget \
    lsb-release \
    gnupg \
    software-properties-common

# Add the official LLVM repository for newer clangd
RUN wget https://apt.llvm.org/llvm.sh && \
    chmod +x llvm.sh && \
    ./llvm.sh 15

# Install build tools and git
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Optionally set up a workspace (for mounting your code)
WORKDIR /workspace

# Expose a port if you want (LSP usually works over stdio, so this is optional)
EXPOSE 8088

# Use clangd-15 as the default command
CMD ["clangd-15"]