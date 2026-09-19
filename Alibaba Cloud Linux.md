**Alibaba Cloud Linux**

一般可以用：

```
sudo yum install -y git
git --version
```

或者：

```
sudo dnf install -y git
git --version
```

安装完成后，建议配置 Git 用户信息，否则 Agent 后面执行 `git commit` 可能失败：

```
git config --global user.name "CODING"
git config --global user.email "coding@example.com"
```

然后确认：

```
git config --global --list
```



```
sudo dnf install -y nodejs npm
```



```
conda create -n aicoding python=3.14 -y
conda activate aicoding
python -m pip install --upgrade pip setuptools wheel -i https://mirrors.aliyun.com/pypi/simple/

pip install -y 各种第三方库 -i https://mirrors.aliyun.com/pypi/simple/
```



```
mkdir -p /opt/coding/workspace/runtimes/python/default
python -m venv /opt/coding/workspace/runtimes/python/default/.venv
source /opt/coding/workspace/runtimes/python/default/.venv/bin/activate

pip install --upgrade pip setuptools wheel -i https://mirrors.aliyun.com/pypi/simple/

deactivate
```





在 Linux 服务器上重新安装前端依赖，不能复用 Windows 的 `node_modules`。

执行：

```
cd /opt/coding/ui
rm -rf node_modules package-lock.json
npm install
```

如果你希望用阿里云 npm 镜像：

```
npm config set registry https://registry.npmmirror.com
npm install
```

然后重新启动：

```
cd /opt/coding
bash scripts/start_ui.sh
```