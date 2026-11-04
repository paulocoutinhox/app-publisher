# Declarative screenshot navigation

The CLI can capture images from Apple simulators, Android devices and macOS. A `ScreenshotPlan` opens each scene's URL, waits for `delay_seconds`, executes each declared action in order and captures the final screen. The app must implement the deep-link routes and load its data deterministically.

```yaml
publication:
  screenshot_plans:
    - platform: android
      device: emulator-5554
      scenes:
        - name: library
          url: exampleapp://library
          output: assets/en-US/android/library.png
          delay_seconds: 1
          actions:
            - kind: tap
              x: 320
              y: 450
            - kind: swipe
              x: 500
              y: 1200
              end_x: 500
              end_y: 550
              duration_ms: 400
            - kind: wait
              seconds: 1
    - platform: ios
      device: YOUR_SIMULATOR_UDID
      scenes:
        - name: reading
          url: exampleapp://reader
          output: assets/en-US/ios/reader.png
          actions:
            - kind: launch
              value: com.example.app
            - kind: wait
              seconds: 0.5
```

`tap`, `swipe` and `text` use `adb shell input` and are Android-only. Android text input is restricted to ASCII letters, numbers, spaces, dots, underscores, hyphens and `@` because `adb input text` cannot reliably enter arbitrary Unicode. Every command is executed as an argument array, without a shell. Apple touch automation requires XCTest/XCUITest in the host application and is **not** emulated by unsupported `simctl` commands.

The CLI does not install applications or automatically select the right emulator. Provision and boot the emulator/simulator before running. Review the generated screenshots before upload, particularly when localization, system alerts, animations or network data could change the view.
