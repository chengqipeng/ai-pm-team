# CentOS 7 安装 Python 3.11 指南

## 前置说明

- CentOS 7 自带 Python 2.7.5，系统 yum 依赖它，**不要修改 `/usr/bin/python`**
- Python 3.10+ 要求 OpenSSL 1.1.1+，CentOS 7 默认是 1.0.2，需安装 `openssl11`
- CentOS 7 默认 GCC 4.8.5 在 PGO 编译时会触发 bug，需去掉 `--enable-optimizations` 或升级 GCC

---

## 步骤一：安装 EPEL 源

```bash
yum install -y epel-release
```

## 步骤二：安装编译依赖

```bash
yum groupinstall -y "Development Tools"
yum install -y openssl11 openssl11-devel bzip2-devel libffi-devel \
  zlib-devel readline-devel sqlite-devel xz-devel tk-devel
```

## 步骤三：设置 OpenSSL 1.1 编译环境变量

```bash
export CFLAGS="-I/usr/include/openssl11"
export LDFLAGS="-L/usr/lib64/openssl11"
```

> 也可以尝试 `pkg-config`：
> ```bash
> export CFLAGS=$(pkg-config --cflags openssl11)
> export LDFLAGS=$(pkg-config --libs openssl11)
> ```

## 步骤四：下载 Python 3.11 源码

```bash
cd /usr/src
curl -O https://www.python.org/ftp/python/3.11.9/Python-3.11.9.tgz
tar xzf Python-3.11.9.tgz
cd Python-3.11.9
```

## 步骤五：编译安装

> ⚠️ **不要使用 `--enable-optimizations`**，CentOS 7 默认 GCC 4.8.5 会导致 PGO 阶段报错：
> `SystemError: <built-in function compile> returned NULL without setting an exception`

```bash
./configure --with-openssl=/usr CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"
make -j$(nproc)
make altinstall
```

> 使用 `altinstall` 而非 `install`，避免覆盖系统 python 命令。

## 步骤六：验证安装

```bash
python3.11 --version
# 输出: Python 3.11.9

pip3.11 --version
```

## 步骤七：配置 python3 命令指向（可选）

```bash
alternatives --install /usr/local/bin/python3 python3 /usr/local/bin/python3.11 2
alternatives --set python3 /usr/local/bin/python3.11
```

验证：

```bash
python3 --version
# 输出: Python 3.11.9
```

---

## 附：如需 PGO 优化（可选）

如果需要 `--enable-optimizations` 带来的性能提升，先升级 GCC：

```bash
yum install -y centos-release-scl
yum install -y devtoolset-11-gcc devtoolset-11-gcc-c++
scl enable devtoolset-11 bash

# 确认 GCC 版本
gcc --version  # 应显示 11.x

# 重新编译
cd /usr/src/Python-3.11.9
make clean
./configure --enable-optimizations --with-openssl=/usr \
  CFLAGS="$CFLAGS" LDFLAGS="$LDFLAGS"
make -j$(nproc)
make altinstall
```

---

## 注意事项

| 事项 | 说明 |
|------|------|
| 不要动 `/usr/bin/python` | yum 依赖 Python 2.7，改了会导致 yum 无法使用 |
| 使用 `altinstall` | 安装为 `python3.11`，不覆盖任何现有命令 |
| OpenSSL 版本 | 必须用 `openssl11`，否则 `_ssl` 模块无法编译 |
| GCC 版本 | 默认 4.8.5 不支持 PGO，去掉优化选项或升级到 devtoolset-11 |
