cmake_minimum_required(VERSION 3.31)
project(RelocationConsumer LANGUAGES C)
if(NOT DEFINED LAB_PREFIX)
  message(FATAL_ERROR "LAB_PREFIX must name the owned fixture install")
endif()
find_package(RelocationFixture CONFIG REQUIRED
  PATHS "${LAB_PREFIX}/lib/cmake/RelocationFixture" NO_DEFAULT_PATH)
add_executable(consumer main.c)
target_link_libraries(consumer PRIVATE RelocationFixture::value)
