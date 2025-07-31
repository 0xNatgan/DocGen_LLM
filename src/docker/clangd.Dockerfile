FROM debian:bullseye-slim

# Install clangd and any build tools you might need
RUN apt-get update && apt-get install -y \
    clangd \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# Optionally set up a workspace (for mounting your code)
WORKDIR /workspace

# Expose a port if you want (LSP usually works over stdio, so this is optional)
EXPOSE 8088

# Default command runs clangd as an LSP server
CMD ["clangd"]