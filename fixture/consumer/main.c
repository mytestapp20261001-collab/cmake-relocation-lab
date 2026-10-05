#include <stdio.h>
#include "value.h"
int main(void) {
  printf("relocation-value=%d\n", relocation_value() + RELOCATION_HEADER_VALUE);
  return 0;
}
