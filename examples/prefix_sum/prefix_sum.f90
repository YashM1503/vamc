subroutine prefix_sum(n, values)
  integer, intent(in) :: n
  real(kind=8), intent(inout) :: values(n)
  integer :: i
  do i = 2, n
    values(i) = values(i - 1) + values(i)
  end do
end subroutine prefix_sum
