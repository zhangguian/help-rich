# ADR-0004: Git push 用 OpenSSL 而非 schannel

## 状态
已采纳(2026-08-01)

## 背景

P2.4 阶段执行"完成节点后推到远程"指令时,`git push origin main` 失败:
```
fatal: unable to access 'https://github.com/zhangguian/help-rich.git/':
schannel: failed to receive handshake, SSL/TLS connection failed
```

但同一时刻 `curl https://github.com/...` 返回 200(2.1s)。说明:
- 网络可达 GitHub
- Windows `curl` 用 OpenSSL,可访问
- Windows `git` 默认用 **schannel**(SChannel),被公司网络拦截 / 拦截后无法 fallback

## 决策

**改用 OpenSSL 作为 git 的 TLS 后端**:

```bash
git config --global http.sslBackend openssl
git config --global http.sslCAInfo "D:\git\Git\mingw64\ssl\certs\ca-bundle.crt"
```

> ⚠️ **重要**:CA bundle 路径**必须匹配实际 git 安装位置**。
> 如果用 `D:\git\Git` 安装的 git,路径是 `D:\git\Git\mingw64\ssl\certs\ca-bundle.crt`
> 如果用 `C:\Program Files\Git` 安装的,路径是 `C:\Program Files\Git\mingw64\ssl\certs\ca-bundle.crt`
> 用 `cmd /c "where git"` + `ls` 验证。

第二次 `git push` 立即成功(`f0438c7..a6a365e main -> main`)。

## 后果

- ✅ `git push` 正常推送
- ✅ `git fetch / pull` 也走 OpenSSL,行为一致
- ⚠️ 全局配置,影响所有 git 仓库
- ⚠️ 团队成员各自配置(`--global` 是个人配置)
- ⚠️ 路径错误会导致 push 失败且报 schannel 错(迷惑性)

## 替代方案(被否决)

| 方案 | 否决理由 |
|---|---|
| 用 SSH key | 个人无 SSH key(Gitee 和内网凭据,GitHub 没有);临时生成 + 上传公钥流程长 |
| 配 HTTP/HTTPS 代理 | 内网代理指向 git.zhhx.top:82(自建),与 GitHub 无关 |
| 关掉 SSL 验证 (`http.sslVerify false`) | 中间人攻击风险;OpenSSL 已经能解决 |
| 推到 Gitee 镜像 | 用户原始仓库是 GitHub,跨平台 push 不是常规流程 |

## 参考

- Git 文档:https://git-scm.com/docs/git-config#Documentation/git-config.txt-httpsslBackend
- StackOverflow: https://stackoverflow.com/q/49111003 (git schannel SSL handshake failed)

## 相关 runbook 条目

`docs/dev-log/runbook.md` 已加入"git push SSL 失败"应急章节。