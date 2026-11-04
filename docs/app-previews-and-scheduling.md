# App Previews, scheduled releases, and tester groups

App Publisher v0.0.1 supports the **App Asset Library** introduced in App Store Connect API 4.5.1. It uses the public `appAssetLibraryVideos`, placement, and ordering APIs, not the deprecated `appPreviewSets` pipeline.

## Apple App Previews

Declare video files under each Apple locale and use placement groups discovered with `app-publisher devices`.

```yaml
locales:
  en-US:
    common:
      name: Example
    apple:
      app_previews:
        IPHONE_DYNAMIC_ISLAND_LARGE_PROFILE:
          - assets/ios/en-US/preview-01.mp4
          - assets/ios/en-US/preview-02.mp4
      preview_frame_timecode: "00:00:03:00"
```

Use `app-publisher validate app.yaml` to validate the local asset paths and counts. `app-publisher sync app.yaml --apply` performs a spec validation with `ffprobe`, reserves a video, uploads parts to the signed URLs, commits the asset, waits for processing, creates the placements, and replaces placements for only those groups explicitly declared in the YAML. The SHA-256 content hash and poster-frame timecode identify reusable assets.

**Requirements:** `ffprobe` must be installed and accessible through `PATH` when applying video uploads. Video frame rate, dimensions, duration, audio requirement, extension, and size are checked against current Apple reference data. The CLI does not transcode or silently change videos.

## Scheduled Apple releases

```yaml
apple:
  versions:
    - platform: IOS
      version: "2.1.0"
      release_type: SCHEDULED
      earliest_release_date: "2027-03-01T14:00:00Z"
```

The release timestamp must be timezone-aware. When creating or modifying a scheduled date, it must be in the future. An unchanged past date can remain in YAML for status checks after the release. A version already in review or released cannot be changed by this operation. If you set `release_type: SCHEDULED`, you must supply `earliest_release_date` before synchronizing.

## Google Play testers independently of releases

```yaml
google:
  package_name: com.example.app
  tester_groups:
    - track: internal
      google_groups:
        - qa-team@example.com
    - track: closed
      google_groups:
        - beta-users@example.com
```

Preview changes with `app-publisher testers app.yaml`. Apply them with `app-publisher testers app.yaml --apply`. This uses the official `edits.testers` resource and commits only changed Google Groups. It does not upload or publish a binary.

The Google Publishing API does not manage individual tester email lists. To avoid silently replacing configured email lists, the CLI accepts only Google Groups and leaves unsupported lists to the Play Console. Do not declare `release.testers` and `tester_groups` for the same track.

## Further references

- [Apple video asset documentation](https://developer.apple.com/documentation/appstoreconnectapi/uploading-and-managing-video-assets)
- [Apple asset placements](https://developer.apple.com/documentation/appstoreconnectapi/placing-assets-on-your-app-store-surfaces)
- [Apple App Store versions](https://developer.apple.com/documentation/appstoreconnectapi/app-store-versions)
- [Google edits.testers](https://developers.google.com/android-publisher/api-ref/rest/v3/edits.testers)
