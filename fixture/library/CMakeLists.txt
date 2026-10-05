cmake_minimum_required(VERSION 3.31)
project(RelocationFixture VERSION 1.0.0 LANGUAGES C)

include(CMakePackageConfigHelpers)
add_library(relocation_fixture STATIC value.c)
set_target_properties(relocation_fixture PROPERTIES EXPORT_NAME value)
target_include_directories(relocation_fixture PUBLIC
  "$<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>"
  "$<INSTALL_INTERFACE:include>")
install(TARGETS relocation_fixture EXPORT RelocationTargets ARCHIVE DESTINATION lib)
install(FILES value.h DESTINATION include)
install(EXPORT RelocationTargets NAMESPACE RelocationFixture::
  DESTINATION lib/cmake/RelocationFixture)
configure_package_config_file(RelocationFixtureConfig.cmake.in
  "${CMAKE_CURRENT_BINARY_DIR}/RelocationFixtureConfig.cmake"
  INSTALL_DESTINATION lib/cmake/RelocationFixture)
install(FILES "${CMAKE_CURRENT_BINARY_DIR}/RelocationFixtureConfig.cmake"
  DESTINATION lib/cmake/RelocationFixture)
