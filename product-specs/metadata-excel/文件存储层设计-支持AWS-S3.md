# 文件存储层设计 — 统一参数体系 + 多云支持

> 本文档基于老项目 core-file 模块的深度分析，设计新项目的文件存储抽象层。
> 核心设计：统一所有云厂商的配置参数为一套通用 key，切换云厂商只改 `type` 一个字段。

## 1. 设计原则

老系统每家云厂商用完全不同的配置 key（`ali-oss-endpoint`、`huawei-obs-endpoint`、`azure-blob-connection-string`...），导致：
- 切换云厂商要改十几个配置项
- 代码中 `FileOsProperties` 有 20+ 个 getter，每家一套
- 新增云厂商要同时改配置解析 + 枚举 + 工厂 + 实现类

新系统的原则：**一套通用参数，所有云厂商共用同一组 key**。每家云厂商只是把通用参数映射到自己 SDK 的对应概念。

## 2. 统一参数定义

### 2.1 通用参数表

| 参数 key | 类型 | 说明 | 哪些厂商用到 |
|:---|:---|:---|:---|
| `type` | String | 存储类型，决定使用哪家实现 | 全部（必填） |
| `endpoint` | String | 服务端点 URL | ALI / HUAWEI / S3 / MINIO / COS |
| `region` | String | 区域/地域 | S3 / COS / ALI |
| `access-key` | String | 访问密钥 ID（AK） | ALI / HUAWEI / S3 / MINIO / COS |
| `secret-key` | String | 访问密钥 Secret（SK） | ALI / HUAWEI / S3 / MINIO / COS |
| `bucket` | String | 存储桶名称 | ALI / HUAWEI / S3 / MINIO / COS |
| `base-url` | String | 文件访问的公网 URL 前缀 | 全部（必填） |
| `connection-string` | String | 连接字符串（Azure 专用） | AZURE |
| `container` | String | 容器名称（Azure 专用，等价于 bucket） | AZURE |
| `path-style-access` | Boolean | 是否使用 Path Style（MinIO 需要 true） | S3 / MINIO |
| `image-process-url` | String | 图片处理服务 URL（CDN/Lambda 等） | AZURE / S3（可选） |
| `local-base-path` | String | 本地存储根目录 | LOCAL |

### 2.2 参数与各云厂商 SDK 概念的映射

| 通用参数 | 阿里 OSS | 腾讯 COS | 华为 OBS | AWS S3 | Azure Blob | MinIO |
|:---|:---|:---|:---|:---|:---|:---|
| `endpoint` | ossEndpoint | — | obsEndpoint | — (由 region 推导) | — | minioEndpoint |
| `region` | — | regionId | — | awsRegion | — | — |
| `access-key` | accessKeyId | secretId | ak | accessKeyId | — | accessKey |
| `secret-key` | accessKeySecret | secretKey | sk | secretAccessKey | — | secretKey |
| `bucket` | bucketName | bucketName | bucketName | bucketName | — | bucketName |
| `connection-string` | — | — | — | — | connectionString | — |
| `container` | — | — | — | — | containerName | — |
| `base-url` | xsyurl | xsyurl | xsyurl | s3 公网 URL | blob 公网 URL | minio 公网 URL |
| `path-style-access` | — | — | — | false | — | true |

### 2.3 type 枚举值

| type 值 | 说明 | 必填参数 |
|:---|:---|:---|
| `local` | 本地文件系统（开发/测试） | `local-base-path` |
| `ali` | 阿里云 OSS | `endpoint` + `access-key` + `secret-key` + `bucket` + `base-url` |
| `cos` | 腾讯云 COS | `region` + `access-key` + `secret-key` + `bucket` + `base-url` |
| `huawei` | 华为云 OBS | `endpoint` + `access-key` + `secret-key` + `bucket` + `base-url` |
| `s3` | AWS S3 | `region` + `access-key` + `secret-key` + `bucket` + `base-url` |
| `minio` | MinIO（S3 兼容） | `endpoint` + `access-key` + `secret-key` + `bucket` + `base-url` |
| `azure` | Azure Blob Storage | `connection-string` + `container` + `base-url` |


## 3. 各场景配置实例

### 3.1 本地开发环境（Local）

```yaml
file:
  storage:
    type: local
    base-url: "http://localhost:8080/files/"
    local-base-path: "/tmp/paas-files/"
```

> 无需任何云账号，文件存储在本地磁盘，适合开发调试。

---

### 3.2 阿里云 OSS

```yaml
file:
  storage:
    type: ali
    endpoint: "https://oss-cn-shanghai.aliyuncs.com"
    access-key: "${ALI_ACCESS_KEY}"
    secret-key: "${ALI_SECRET_KEY}"
    bucket: "neocrm-prod"
    base-url: "https://neocrm-prod.oss-cn-shanghai.aliyuncs.com/"
```

> `endpoint` 是阿里 OSS 的 Region Endpoint，不含 bucket 名。
> `base-url` 是文件的公网访问前缀，通常是 `https://{bucket}.{endpoint}/`。

---

### 3.3 腾讯云 COS

```yaml
file:
  storage:
    type: cos
    region: "ap-shanghai"
    access-key: "${COS_SECRET_ID}"
    secret-key: "${COS_SECRET_KEY}"
    bucket: "neocrm-1250000000"
    base-url: "https://neocrm-1250000000.cos.ap-shanghai.myqcloud.com/"
```

> 腾讯 COS 的 `bucket` 格式是 `{name}-{appid}`。
> `region` 对应 COS 的 Region（如 ap-shanghai、ap-guangzhou）。

---

### 3.4 华为云 OBS

```yaml
file:
  storage:
    type: huawei
    endpoint: "https://obs.cn-east-3.myhuaweicloud.com"
    access-key: "${HW_ACCESS_KEY}"
    secret-key: "${HW_SECRET_KEY}"
    bucket: "neocrm-prod"
    base-url: "https://neocrm-prod.obs.cn-east-3.myhuaweicloud.com/"
```

> `endpoint` 是华为 OBS 的 Region Endpoint。

---

### 3.5 AWS S3

```yaml
file:
  storage:
    type: s3
    region: "ap-northeast-1"
    access-key: "${AWS_ACCESS_KEY_ID}"
    secret-key: "${AWS_SECRET_ACCESS_KEY}"
    bucket: "neocrm-prod"
    base-url: "https://neocrm-prod.s3.ap-northeast-1.amazonaws.com/"
```

> AWS S3 不需要 `endpoint`，SDK 根据 `region` 自动推导。
> `base-url` 格式：`https://{bucket}.s3.{region}.amazonaws.com/`。

---

### 3.6 AWS S3（中国区 / GovCloud）

```yaml
file:
  storage:
    type: s3
    region: "cn-north-1"
    endpoint: "https://s3.cn-north-1.amazonaws.com.cn"
    access-key: "${AWS_CN_ACCESS_KEY}"
    secret-key: "${AWS_CN_SECRET_KEY}"
    bucket: "neocrm-cn"
    base-url: "https://neocrm-cn.s3.cn-north-1.amazonaws.com.cn/"
```

> 中国区需要显式指定 `endpoint`，因为域名后缀是 `.com.cn`。

---

### 3.7 MinIO（S3 兼容 / 私有化部署）

```yaml
file:
  storage:
    type: minio
    endpoint: "http://192.168.1.100:9000"
    access-key: "minioadmin"
    secret-key: "minioadmin"
    bucket: "neocrm"
    base-url: "http://192.168.1.100:9000/neocrm/"
    path-style-access: true
```

> MinIO 必须设置 `path-style-access: true`，因为 MinIO 不支持 Virtual-Hosted Style。
> `endpoint` 是 MinIO 服务地址。
> `base-url` 格式：`{endpoint}/{bucket}/`。

---

### 3.8 Azure Blob Storage

```yaml
file:
  storage:
    type: azure
    connection-string: "DefaultEndpointsProtocol=https;AccountName=neocrm;AccountKey=xxx;EndpointSuffix=core.windows.net"
    container: "files"
    base-url: "https://neocrm.blob.core.windows.net/files/"
    image-process-url: "https://neocrm-cdn.azureedge.net/files/"
```

> Azure 使用 `connection-string` 而非 AK/SK，这是 Azure SDK 的标准认证方式。
> `container` 等价于其他厂商的 `bucket`。
> `image-process-url` 可选，配置后图片 URL 走 CDN + 图片处理。

---

### 3.9 阿里云 OSS + CDN 加速

```yaml
file:
  storage:
    type: ali
    endpoint: "https://oss-cn-shanghai.aliyuncs.com"
    access-key: "${ALI_ACCESS_KEY}"
    secret-key: "${ALI_SECRET_KEY}"
    bucket: "neocrm-prod"
    base-url: "https://cdn.neocrm.com/"
    image-process-url: "https://cdn.neocrm.com/"
```

> `base-url` 指向 CDN 域名而非 OSS 直连域名，CDN 回源到 OSS。
> 上传仍然直连 OSS（通过 `endpoint`），下载/访问走 CDN。

## 4. Java 配置类设计

### 4.1 统一配置属性类

```java
@Data
@ConfigurationProperties(prefix = "file.storage")
public class FileStorageProperties {

    /** 存储类型：local / ali / cos / huawei / s3 / minio / azure */
    private String type = "local";

    /** 服务端点 URL */
    private String endpoint;

    /** 区域 */
    private String region;

    /** 访问密钥 ID */
    private String accessKey;

    /** 访问密钥 Secret */
    private String secretKey;

    /** 存储桶名称 */
    private String bucket;

    /** 文件公网访问 URL 前缀 */
    private String baseUrl;

    /** Azure 连接字符串 */
    private String connectionString;

    /** Azure 容器名 */
    private String container;

    /** Path Style Access（MinIO 需要 true） */
    private boolean pathStyleAccess = false;

    /** 图片处理服务 URL（CDN/Lambda 等） */
    private String imageProcessUrl;

    /** 本地存储根目录 */
    private String localBasePath = "/tmp/paas-files/";
}
```

### 4.2 工厂类

```java
@Configuration
@EnableConfigurationProperties(FileStorageProperties.class)
public class FileStorageAutoConfiguration {

    @Bean
    @ConditionalOnMissingBean
    public FileStorageService fileStorageService(FileStorageProperties props) {
        switch (props.getType()) {
            case "local":  return new LocalFileStorage(props);
            case "ali":    return new AliyunOssStorage(props);
            case "cos":    return new TencentCosStorage(props);
            case "huawei": return new HuaweiObsStorage(props);
            case "s3":     return new AwsS3Storage(props);
            case "minio":  return new MinioStorage(props);
            case "azure":  return new AzureBlobStorage(props);
            default:
                throw new IllegalArgumentException(
                    "不支持的存储类型: " + props.getType()
                    + "，可选值: local/ali/cos/huawei/s3/minio/azure");
        }
    }
}
```

### 4.3 各实现类如何读取统一参数

```java
// ── 阿里云 OSS ──
public class AliyunOssStorage extends AbstractFileStorage {
    private final OSS ossClient;

    public AliyunOssStorage(FileStorageProperties props) {
        super(props);
        this.ossClient = new OSSClientBuilder().build(
            props.getEndpoint(),       // 通用参数 endpoint
            props.getAccessKey(),      // 通用参数 access-key
            props.getSecretKey());     // 通用参数 secret-key
    }

    @Override
    protected void doPut(String key, File file) {
        ossClient.putObject(props.getBucket(), key, file);  // 通用参数 bucket
    }
}

// ── 腾讯云 COS ──
public class TencentCosStorage extends AbstractFileStorage {
    private final COSClient cosClient;

    public TencentCosStorage(FileStorageProperties props) {
        super(props);
        COSCredentials cred = new BasicCOSCredentials(
            props.getAccessKey(),      // 通用参数 access-key → COS secretId
            props.getSecretKey());     // 通用参数 secret-key → COS secretKey
        ClientConfig config = new ClientConfig(
            new Region(props.getRegion()));  // 通用参数 region
        this.cosClient = new COSClient(cred, config);
    }
}

// ── AWS S3 ──
public class AwsS3Storage extends AbstractFileStorage {
    private final S3Client s3Client;

    public AwsS3Storage(FileStorageProperties props) {
        super(props);
        S3ClientBuilder builder = S3Client.builder()
            .region(Region.of(props.getRegion()))     // 通用参数 region
            .credentialsProvider(StaticCredentialsProvider.create(
                AwsBasicCredentials.create(
                    props.getAccessKey(),              // 通用参数 access-key
                    props.getSecretKey())));            // 通用参数 secret-key

        if (props.getEndpoint() != null && !props.getEndpoint().isEmpty()) {
            builder.endpointOverride(URI.create(props.getEndpoint()));
        }
        this.s3Client = builder.build();
    }
}

// ── MinIO（复用 S3 SDK，只是参数不同） ──
public class MinioStorage extends AwsS3Storage {

    public MinioStorage(FileStorageProperties props) {
        super(overrideForMinio(props));
    }

    private static FileStorageProperties overrideForMinio(FileStorageProperties props) {
        props.setPathStyleAccess(true);  // MinIO 强制 Path Style
        if (props.getRegion() == null || props.getRegion().isEmpty()) {
            props.setRegion("us-east-1"); // MinIO 默认 region
        }
        return props;
    }
}

// ── Azure Blob ──
public class AzureBlobStorage extends AbstractFileStorage {
    private final BlobContainerClient containerClient;

    public AzureBlobStorage(FileStorageProperties props) {
        super(props);
        BlobServiceClient serviceClient = new BlobServiceClientBuilder()
            .connectionString(props.getConnectionString())  // Azure 专用参数
            .buildClient();
        this.containerClient = serviceClient
            .getBlobContainerClient(props.getContainer());   // Azure 专用参数
    }
}

// ── 华为云 OBS ──
public class HuaweiObsStorage extends AbstractFileStorage {
    private final ObsClient obsClient;

    public HuaweiObsStorage(FileStorageProperties props) {
        super(props);
        this.obsClient = new ObsClient(
            props.getAccessKey(),      // 通用参数 access-key
            props.getSecretKey(),      // 通用参数 secret-key
            props.getEndpoint());      // 通用参数 endpoint
    }
}
```

### 4.4 AbstractFileStorage 基类

```java
public abstract class AbstractFileStorage implements FileStorageService {

    protected final FileStorageProperties props;

    protected AbstractFileStorage(FileStorageProperties props) {
        this.props = props;
    }

    @Override
    public String upload(File file, String tenantId, String fileGroup) {
        String key = FilePathGenerator.generate(tenantId, fileGroup, getExt(file));
        doPut(key, file);
        return key;
    }

    @Override
    public String getUrl(String ossPath) {
        String baseUrl = props.getBaseUrl();
        if (baseUrl.endsWith("/") && ossPath.startsWith("/")) {
            return baseUrl + ossPath.substring(1);
        }
        if (!baseUrl.endsWith("/") && !ossPath.startsWith("/")) {
            return baseUrl + "/" + ossPath;
        }
        return baseUrl + ossPath;
    }

    @Override
    public String getImageUrl(String ossPath, int width, int height) {
        String url = getUrl(ossPath);
        // 子类可覆写，追加云厂商特定的图片处理参数
        return url;
    }

    protected abstract void doPut(String key, File file);
    protected abstract void doGet(String key, File target);
    protected abstract void doDelete(String key);

    // ... download / delete 等模板方法
}
```

## 5. 图片处理参数统一

各云厂商的图片缩略图参数格式不同，统一为方法参数，由各实现类拼接：

| 云厂商 | 缩略图 URL 格式 | WebP 压缩格式 |
|:---|:---|:---|
| 阿里 OSS | `?x-oss-process=image/resize,m_fill,h_{h},w_{w}` | `?x-oss-process=image/format,webp` |
| 腾讯 COS | `?imageMogr2/thumbnail/{w}x{h}` | `?imageMogr2/format/webp` |
| 华为 OBS | `?x-image-process=image/resize,m_lfit,h_{h},w_{w}` | `?x-image-process=image/format,webp` |
| AWS S3 | 不支持（需 CloudFront + Lambda） | 不支持 |
| MinIO | 不支持 | 不支持 |
| Azure | 需配置 `image-process-url` + CDN 规则 | 需 CDN 规则 |
| Local | 不支持 | 不支持 |

```java
// AliyunOssStorage
@Override
public String getImageUrl(String ossPath, int width, int height) {
    return getUrl(ossPath) + "?x-oss-process=image/resize,m_fill,h_"
        + height + ",w_" + width;
}

// TencentCosStorage
@Override
public String getImageUrl(String ossPath, int width, int height) {
    return getUrl(ossPath) + "?imageMogr2/thumbnail/" + width + "x" + height;
}

// AwsS3Storage / MinioStorage / LocalFileStorage
@Override
public String getImageUrl(String ossPath, int width, int height) {
    // 不支持服务端图片处理，返回原图
    return getUrl(ossPath);
}
```

## 6. 统一接口定义

```java
public interface FileStorageService {

    /** 上传文件，返回 OSS 相对路径 */
    String upload(File file, String tenantId, String fileGroup);

    /** 上传流，返回 OSS 相对路径 */
    String upload(InputStream inputStream, String fileName,
                  String tenantId, String fileGroup);

    /** 下载到本地临时文件 */
    File download(String ossPath);

    /** 删除 */
    void delete(String ossPath);

    /** 获取公网访问 URL */
    String getUrl(String ossPath);

    /** 获取图片 URL（含缩略图参数，不支持的厂商返回原图） */
    String getImageUrl(String ossPath, int width, int height);

    /** 获取带签名的临时下载 URL */
    String getSignedUrl(String ossPath, int expireMinutes);

    /** 获取当前存储类型 */
    String getType();
}
```

## 7. 老系统参数 → 新系统参数迁移对照

供迁移时参考，老 Nacos JSON key 如何映射到新 YAML key：

| 老系统 Nacos key | 新系统 YAML key | 说明 |
|:---|:---|:---|
| `fileos-properties-ostype` | `file.storage.type` | 值也变了：`txcos`→`cos`，`ali`→`ali`，`azure.blob`→`azure` |
| `fileos-properties-xsyurl` | `file.storage.base-url` | — |
| `fileos-properties-secretid` | `file.storage.access-key` | 腾讯 COS 的 secretId |
| `fileos-properties-secretkey` | `file.storage.secret-key` | 腾讯 COS 的 secretKey |
| `fileos-properties-bucketname` | `file.storage.bucket` | — |
| `fileos-properties-regionid` | `file.storage.region` | — |
| `fileos-properties-appid` | ❌ 废弃 | COS bucket 名已含 appid |
| `fileos-properties-baseurl` | ❌ 废弃 | 统一用 base-url |
| `ali-oss-endpoint` | `file.storage.endpoint` | — |
| `ali-oss-access-id` | `file.storage.access-key` | — |
| `ali-oss-access-secret` | `file.storage.secret-key` | — |
| `ali-bucketname` | `file.storage.bucket` | — |
| `huawei-obs-endpoint` | `file.storage.endpoint` | — |
| `huawei-obs-access-key` | `file.storage.access-key` | — |
| `huawei-obs-secret-key` | `file.storage.secret-key` | — |
| `huawei-obs-bucket` | `file.storage.bucket` | — |
| `azure-blob-connection-string` | `file.storage.connection-string` | — |
| `azure-blob-container-name` | `file.storage.container` | — |
| `azure-blob-img-process-url` | `file.storage.image-process-url` | — |
| `fileos-properties-pressure` | ❌ 废弃 | 图片压缩改为按需调用 |
| `fileos-properties-pressure_notin` | ❌ 废弃 | 不再依赖 User-Agent 判断 |

## 8. 新项目目录结构

```
service/
└── common/
    └── storage/
        ├── FileStorageService.java            # 🔑 统一接口（7 个方法）
        ├── FileStorageProperties.java         # 🔑 统一配置属性（12 个字段）
        ├── FileStorageAutoConfiguration.java   # Spring Boot 自动配置 + 工厂
        ├── AbstractFileStorage.java            # 模板方法基类
        ├── FilePathGenerator.java              # 路径生成工具
        └── impl/
            ├── LocalFileStorage.java           # 本地（开发/测试）
            ├── AliyunOssStorage.java           # 阿里云 OSS
            ├── TencentCosStorage.java          # 腾讯云 COS
            ├── HuaweiObsStorage.java           # 华为云 OBS
            ├── AwsS3Storage.java               # AWS S3
            ├── MinioStorage.java               # MinIO（继承 AwsS3Storage）
            └── AzureBlobStorage.java           # Azure Blob
```

## 9. 实施计划

| 阶段 | 内容 |
|:---|:---|
| Phase 1 | FileStorageService 接口 + FileStorageProperties + LocalFileStorage + AwsS3Storage |
| Phase 2 | 导入导出框架集成 FileStorageService，替换所有 TODO |
| Phase 3 | 迁移 AliyunOssStorage / TencentCosStorage / HuaweiObsStorage / AzureBlobStorage |
| Phase 4 | MinioStorage + 私有化部署验证 |
| Phase 5 | 图片处理增强（CloudFront / CDN 集成） |
