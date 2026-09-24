# Independent RTX Super Resolution and Safe Multipass Implementation Plan

1. Extend Home Agent option validation with independent `dlss_enabled`, `rtx_vsr_enabled`, and `multipass_protection` fields while mapping legacy `upscaler` requests.
2. Add a pure protected-neural-settings helper and unit tests for every pass count and raw bypass.
3. Update job capability checks, media validation, runner arguments, and progress accounting for one to three enabled stages.
4. Update the isolated runner to execute interpolation, DLSS5, and RTX VSR independently in the documented order.
5. Redesign the Enhance sidebar so DLSS5 and RTX Super Resolution are separate optional sections; default interpolation off, DLSS5 to one pass, and RTX Super Resolution off.
6. Add source-dimension probing in the browser and display the expected RTX output dimensions.
7. Update backend, runner, and UI tests, then run focused tests, JavaScript syntax validation, Python compilation, and the broader suite.
8. Run local RTX smoke tests for RTX VSR-only, DLSS5 plus RTX VSR, and protected two-pass DLSS5 when a suitable short source is available.
9. Commit the implementation, push it, verify the deployment workflow, restart the Home Agent, and confirm advertised capabilities.
